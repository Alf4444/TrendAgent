"""
etf_spejder.py — Automatisk ETF-screener for TrendAgent
=========================================================
Henter alle UCITS ETF'er fra justETF, filtrerer og scorer dem
baseret på momentum-signaler. Gemmer top-kandidater til
data/etf_spejder_hits.json som bruges af etf_weekly.html.

Køres som del af etf_weekly workflow (lørdag).

Krav til en kandidat:
  - UCITS long-only ETF handlet på Xetra
  - Akkumulerende (ingen løbende udbytteskat)
  - Min. 50M EUR AUM (likviditet)
  - Maks 1.0% TER
  - BULL-trend (kurs over MA)
  - Positiv momentum

Scoring (0-6 point):
  +2  Momentum > 5% over bedste MA
  +2  Golden Cross (MA20 krydser MA50 opad)
  +1  RSI under 70 (ikke overkøbt)
  +1  1M afkast positiv
"""

import json
import random
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import justetf_scraping
except ImportError:
    print("❌ justetf_scraping ikke installeret.")
    print("   Kør: pip install git+https://github.com/druzsan/justetf-scraping.git")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance ikke installeret. Kør: pip install yfinance")
    sys.exit(1)

from utils import get_ma, get_best_ma, get_rsi, get_cross_signal, get_trend_state
from sector_heatmap import build_portfolio_correlation

# ==========================================
# KONFIGURATION
# ==========================================
ROOT             = Path(__file__).resolve().parents[1]
WATCHLIST_FILE   = ROOT / "config/etf_watchlist.json"
PORTFOLIO_FILE   = ROOT / "config/etf_portfolio.json"
HITS_FILE        = ROOT / "data/etf_spejder_hits.json"
PREV_HITS_FILE   = ROOT / "data/etf_spejder_prev.json"  # Forrige uges hits
SOLD_FILE        = ROOT / "data/etf_sold.json"           # Solgte fonde — cool-off filter
HISTORY_FILE     = ROOT / "data/etf_history.json"        # Kurshistorik til korrelationsberegning
NORDNET_FILE     = ROOT / "data/etf_nordnet_inventory.json"
ASK_ELIGIBLE_FILE = ROOT / "config/etf_ask_eligible.json"  # Skats positivliste — opdateres maj hvert år

# Filtre
MIN_AUM_EUR      = 50_000_000   # Min 50M EUR
MAX_TER          = 1.0          # Maks 1% TER
REQUIRE_ACC      = True         # Kun akkumulerende

# Scoring
MIN_SCORE             = 2     # Minimum score for at komme med
MIN_MOMENTUM_PCT      = 5.0   # Min % over MA (stabile)
MAX_RSI               = 70    # Ikke overkøbt (stabile)
MAX_CANDIDATES_STABIL = 10    # Max stabile trendere
MAX_CANDIDATES_HURTIG = 10    # Max hurtige heste

# Hurtig hest grænser
HURTIG_MIN_MOMENTUM   = 20.0  # Min % over MA
HURTIG_MIN_1Y         = 50.0  # Min 1-årsafkast

# Pause mellem yfinance-kald for at undgå rate limiting
YFINANCE_DELAY   = 0.3


# ==========================================
# HJÆLPEFUNKTIONER
# ==========================================

def load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Filtrer kommentar-felter
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if not k.startswith('_')}
            return data
    except Exception as e:
        print(f"⚠️  Kunne ikke læse {path}: {e}")
        return default

def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_nordnet_inventory():
    """
    Indlæser Nordnet-inventory fra data/etf_nordnet_inventory.json.
    Returnerer et set af ISINs der kan handles på Nordnet,
    eller None hvis filen ikke eksisterer (filteret deaktiveres da).

    Format: {"ISIN": {"name": "...", "isin": "..."}, ...}
    """
    if not NORDNET_FILE.exists():
        print(f"⚠️  Nordnet-inventory ikke fundet: {NORDNET_FILE.name}")
        print(f"   Nordnet-filter deaktiveret — alle ISINs scannes.")
        return None
    try:
        with open(NORDNET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        isins = set(data.keys())
        print(f"✅ Nordnet-inventory indlæst: {len(isins):,} handlbare ETF'er")
        return isins
    except Exception as e:
        print(f"⚠️  Kunne ikke læse Nordnet-inventory: {e}")
        print(f"   Nordnet-filter deaktiveret — alle ISINs scannes.")
        return None


def load_sold_funds():
    """
    Indlæser etf_sold.json — liste af solgte fonde til cool-off filter.

    Format:
      { "ISIN": { "sold_date": "YYYY-MM-DD", "sold_price": 123.45 }, ... }

    Returnerer dict eller {} hvis filen ikke eksisterer.
    """
    if not SOLD_FILE.exists():
        return {}
    try:
        with open(SOLD_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}


def is_sold_cooloff(isin, ticker, sold_funds, prices):
    """
    Returnerer True hvis fonden er i cool-off efter salg og skal filtreres fra.

    Cool-off ophører når BEGGE betingelser er opfyldt:
      1. Kursen er tilbage i BULL-trend (over MA)
      2. Kursen er højere end salgskursen

    Logik:
      - Ejede fonde (is_owned=True) er aldrig i cool-off
      - Fonde ikke i sold_funds er aldrig i cool-off
      - Fonde der mangler prisdata filtreres ikke (vi kan ikke vurdere)
    """
    if not isin or isin not in sold_funds:
        return False

    entry      = sold_funds[isin]
    sold_price = entry.get("sold_price", 0)

    if not prices or not sold_price:
        return False

    curr_price = prices[-1]

    # Betingelse 1: BULL-trend (kurs over MA)
    from utils import get_best_ma
    ma_val, _ = get_best_ma(prices)
    if ma_val is None or curr_price <= ma_val:
        print(f"   ⏳ Cool-off: {isin} — under MA ({curr_price:.2f} <= {ma_val:.2f if ma_val else '?'})")
        return True

    # Betingelse 2: Kurs højere end salgskurs
    if curr_price <= sold_price:
        print(f"   ⏳ Cool-off: {isin} — under salgskurs ({curr_price:.2f} <= {sold_price:.2f})")
        return True

    # Begge betingelser opfyldt — cool-off ophørt
    print(f"   ✅ Cool-off ophørt: {isin} — BULL og over salgskurs ({curr_price:.2f} > {sold_price:.2f})")
    return False


def load_ask_eligible():
    """
    Indlæser Skats positivliste fra config/etf_ask_eligible.json.
    Returnerer et set af ISINs der er ASK-egnede, eller tomt set hvis filen mangler.
    Filen opdateres manuelt én gang om året (typisk maj).
    """
    if not ASK_ELIGIBLE_FILE.exists():
        print(f"⚠️  ASK-positivliste ikke fundet: {ASK_ELIGIBLE_FILE.name}")
        print(f"   ASK-egnethed sættes til None for alle kandidater.")
        return set()
    try:
        with open(ASK_ELIGIBLE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        isins = set(data.get("isins", []))
        updated = data.get("_opdateret", "ukendt")
        print(f"✅ ASK-positivliste indlæst: {len(isins):,} ISINs (opdateret: {updated})")
        return isins
    except Exception as e:
        print(f"⚠️  Kunne ikke læse ASK-positivliste: {e}")
        return set()


def is_nordnet_available(isin, nordnet_isins, is_owned, is_watchlist):
    """
    Returnerer True hvis fonden må vises i Spejder-output.

    Regler (i prioriteret rækkefølge):
      1. Fonde vi ejer → ALTID vis (uanset inventory)
      2. Fonde på watchlist → ALTID vis (de er verificerede)
      3. Nordnet-filter aktivt → kun hvis ISIN er i inventory
      4. Nordnet-filter ikke aktivt (fil mangler) → vis alle
    """
    if is_owned:
        return True
    if is_watchlist:
        return True
    if nordnet_isins is None:
        return True  # Filter deaktiveret
    return isin in nordnet_isins


def get_yfinance_ticker(isin, name):
    """
    Konverterer ISIN til yfinance ticker.
    Forsøger først ISIN direkte, derefter navnesøgning.
    Returnerer ticker-streng eller None.
    """
    # Strategi 1: Søg via yfinance search
    try:
        results = yf.Search(isin, max_results=3)
        if hasattr(results, 'quotes') and results.quotes:
            for q in results.quotes:
                ticker = q.get('symbol', '')
                # Foretræk .DE (Xetra) tickers
                if ticker.endswith('.DE'):
                    return ticker
            # Tag første resultat hvis ingen .DE
            return results.quotes[0].get('symbol')
    except Exception:
        pass

    # Strategi 2: Konstruer ticker fra ISIN via justETF
    # justETF ISIN-profil indeholder typisk ticker-info
    return None


def calculate_weighted_momentum(row):
    """
    Beregner tidsvægtet momentum-score baseret på afkast over
    flere tidshorisonter. Nyere perioder vægtes tungere.

    Normaliseret til månedligt afkast for fair sammenligning:
      1M afkast           → ganges med 4 (høj vægt — nuværende momentum)
      3M afkast / 3       → ganges med 2 (middel vægt)
      6M afkast / 6       → ganges med 1 (lav vægt — historisk)

    Returnerer (weighted_score, consistency_bonus, details_dict)
    """
    r1m = row.get('last_month')   or row.get('month1')
    r3m = row.get('last_three_months') or row.get('month3')
    r6m = row.get('last_six_months')   or row.get('month6')

    try:
        r1m = float(r1m) if r1m is not None else None
        r3m = float(r3m) if r3m is not None else None
        r6m = float(r6m) if r6m is not None else None
    except Exception:
        r1m = r3m = r6m = None

    # Normaliser til månedligt afkast
    r1m_monthly = r1m                    if r1m is not None else None
    r3m_monthly = (r3m / 3)              if r3m is not None else None
    r6m_monthly = (r6m / 6)              if r6m is not None else None

    # Vejede score — kræver mindst 1M data
    if r1m_monthly is None:
        return 0, 0, {}

    weighted = r1m_monthly * 4
    if r3m_monthly is not None:
        weighted += r3m_monthly * 2
    if r6m_monthly is not None:
        weighted += r6m_monthly * 1

    # Konsistens-bonus
    consistency_bonus = 0
    reasons_bonus = []
    available = [x for x in [r1m_monthly, r3m_monthly, r6m_monthly] if x is not None]

    # Bonus A: Alle tilgaengelige perioder er positive
    if available and all(x > 0 for x in available):
        consistency_bonus += 1
        reasons_bonus.append("Konsistent positiv på alle tidshorisonter")

    # Bonus B: Acceleration — nyere periode er bedre end aeldre
    if r1m_monthly is not None and r3m_monthly is not None and r6m_monthly is not None:
        if r1m_monthly > r3m_monthly > r6m_monthly:
            consistency_bonus += 2
            reasons_bonus.append(f"Accelererende trend: {r6m_monthly:.1f}% → {r3m_monthly:.1f}% → {r1m_monthly:.1f}% pr. md.")
        elif r1m_monthly > r3m_monthly:
            consistency_bonus += 1
            reasons_bonus.append(f"Momentum tiltagende: {r3m_monthly:.1f}% → {r1m_monthly:.1f}% pr. md.")

    details = {
        "r1m_monthly": round(r1m_monthly, 2) if r1m_monthly else None,
        "r3m_monthly": round(r3m_monthly, 2) if r3m_monthly else None,
        "r6m_monthly": round(r6m_monthly, 2) if r6m_monthly else None,
        "weighted":    round(weighted, 2),
        "bonus":       consistency_bonus,
        "bonus_reasons": reasons_bonus,
    }
    return weighted, consistency_bonus, details


def fetch_prices(ticker, months=12):
    """
    Henter historiske kurser via yfinance.
    Returnerer liste af daglige lukningskurser (nyeste sidst).
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=f"{months}mo", auto_adjust=True)
        if hist.empty:
            return []
        return [round(float(p), 4) for p in hist['Close'].dropna().tolist()]
    except Exception:
        return []


# ==========================================
# HENT UNIVERSE FRA JUSTÉTF
# ==========================================

def fetch_universe():
    """
    Henter alle relevante ETF'er fra justETF.
    Filtrerer på AUM, TER og type.
    Returnerer DataFrame med ISIN, navn, afkast, TER osv.
    """
    print("📡 Henter ETF-univers fra justETF...")

    try:
        df = justetf_scraping.load_overview(strategy="epg-longOnly")
        print(f"   Hentet {len(df)} ETF'er i alt")
    except Exception as e:
        print(f"❌ justETF fejlede: {e}")
        return None

    # Filtrer på tilgængelige kolonner
    print(f"   Tilgængelige kolonner: {list(df.columns)}")

    # AUM filter
    if 'fundSize' in df.columns:
        df = df[df['fundSize'] >= MIN_AUM_EUR]
        print(f"   Efter AUM-filter (>{MIN_AUM_EUR/1e6:.0f}M EUR): {len(df)} ETF'er")
    elif 'aum' in df.columns:
        df = df[df['aum'] >= MIN_AUM_EUR]
        print(f"   Efter AUM-filter: {len(df)} ETF'er")

    # TER filter
    ter_col = next((c for c in ['ter', 'totalExpenseRatio'] if c in df.columns), None)
    if ter_col:
        df = df[df[ter_col].notna() & (df[ter_col] <= MAX_TER)]
        print(f"   Efter TER-filter (<={MAX_TER}%): {len(df)} ETF'er")

    # Akkumulerende filter
    if REQUIRE_ACC and 'distributionPolicy' in df.columns:
        df = df[df['distributionPolicy'].str.lower().str.contains('acc|accumul', na=False)]
        print(f"   Efter akkumulerende-filter: {len(df)} ETF'er")
    elif REQUIRE_ACC and 'incomeType' in df.columns:
        df = df[df['incomeType'].str.lower().str.contains('acc|accumul', na=False)]
        print(f"   Efter akkumulerende-filter: {len(df)} ETF'er")

    # Xetra-filter — kun ETF'er noteret på Xetra (.DE tickers)
    # Nordnet handler primært Xetra-listede ETF'er, og dette skærer
    # universet markant ned og sikrer vi kun får handlbare tickers
    ticker_col_check = next((c for c in ['ticker', 'Ticker'] if c in df.columns), None)
    exchange_col = next((c for c in ['exchange', 'exchanges', 'primaryExchange', 'listingExchange'] if c in df.columns), None)
    if exchange_col:
        before = len(df)
        df = df[df[exchange_col].str.upper().str.contains('XETRA|XETR|GER|ETR', na=False)]
        print(f"   Efter Xetra-filter (exchange): {len(df)} ETF'er (fra {before})")
    elif ticker_col_check:
        before = len(df)
        mask = (
            df[ticker_col_check].str.upper().str.endswith('.DE') |
            ~df[ticker_col_check].str.contains('.', regex=False, na=True)
        )
        df = df[mask]
        print(f"   Efter Xetra-filter (ticker .DE): {len(df)} ETF'er (fra {before})")
    else:
        print(f"   ⚠️  Xetra-filter: ingen exchange/ticker-kolonne — filter sprunget over")

    print(f"   Endeligt univers: {len(df)} ETF'er")
    return df


# ==========================================
# SCORE EN ETF
# ==========================================

def score_etf(isin, name, row, prices, is_owned, is_watchlist):
    """
    Beregner Spejder-score baseret på tekniske signaler.
    Returnerer score-dict eller None hvis ikke kvalificeret.
    """
    if len(prices) < 20:
        return None

    ma_val, ma_label = get_best_ma(prices)
    if not ma_val:
        return None

    curr = prices[-1]
    momentum = round(((curr / ma_val) - 1) * 100, 2)
    trend    = get_trend_state(prices)
    rsi      = get_rsi(prices, 14)
    cross    = get_cross_signal(prices)

    # Hurtige heste: ingen RSI-krav, høj momentum er nok
    # Stabile trendere: kræver RSI < 70 og momentum 5-20%
    is_hurtig = momentum >= HURTIG_MIN_MOMENTUM or (
        rsi is not None and False  # 1Y tjekkes i return-blokken
    )

    # Kræv BULL-trend og minimum momentum
    if trend != "BULL" or momentum < MIN_MOMENTUM_PCT:
        return None

    # Stabile: fjern overkøbte
    if not is_hurtig and rsi is not None and rsi >= MAX_RSI:
        return None

    # Beregn score
    score   = 0
    reasons = []

    # Momentum
    score += 2
    reasons.append(f"Momentum +{momentum:.1f}% over {ma_label}")

    # Golden Cross
    if cross == "🚀 GOLDEN":
        score += 2
        reasons.append("Golden Cross — MA20 krydser MA50 opad")

    # RSI ikke overkøbt
    if rsi is not None and rsi < MAX_RSI:
        score += 1
        reasons.append(f"RSI {rsi:.0f} — ikke overkøbt")
    elif rsi is None:
        score += 1  # Ingen data er ikke diskvalificerende

    # 1M afkast
    # Afkast fra justETF kolonner
    return_1m_raw = row.get('last_month') or row.get('month1') or row.get('return1month') or row.get('1m')
    return_1y_raw = row.get('last_year')  or row.get('year1')  or row.get('return1year')  or row.get('1y')
    ter_raw       = row.get('ter') or row.get('totalExpenseRatio') or 0

    try:
        return_1m = float(return_1m_raw) if return_1m_raw is not None else None
    except Exception:
        return_1m = None

    if return_1m and return_1m > 0:
        score += 1
        reasons.append(f"1M afkast: +{return_1m:.1f}%")

    # Tidsvagtet momentum + konsistens-bonus
    weighted_score, consistency_bonus, momentum_details = calculate_weighted_momentum(row)
    score += consistency_bonus

    if momentum_details.get('bonus_reasons'):
        for br in momentum_details['bonus_reasons']:
            reasons.append(br)

    if score < MIN_SCORE:
        return None

    # Bestem kategori
    return_1y_val = round(float(return_1y_raw), 2) if return_1y_raw is not None else 0
    if momentum >= HURTIG_MIN_MOMENTUM or return_1y_val >= HURTIG_MIN_1Y:
        kategori = "hurtig"
    else:
        kategori = "stabil"

    return {
        "isin":        row.get('_effective_isin') or row.get('_isin') or isin,
        "name":        name,
        "ticker":      row.get('_ticker', ''),
        "score":       score,
        "weighted_momentum": round(weighted_score, 2),
        "consistency_bonus": consistency_bonus,
        "kategori":    kategori,
        "momentum":    momentum,
        "ma_label":    ma_label,
        "trend":       trend,
        "rsi":         round(rsi, 1) if rsi else None,
        "cross":       cross,
        "return_1m":   round(return_1m, 2) if return_1m is not None else None,
        "return_1y":   return_1y_val if return_1y_raw is not None else None,
        "short_history": return_1y_raw is None,  # Mangler 1Y data — for ny fond
        "ter":         round(float(ter_raw), 2) if ter_raw else None,
        "is_owned":    is_owned,
        "is_watchlist": is_watchlist,
        "reasons":     reasons,
        "scanned_at":  datetime.now().strftime('%Y-%m-%d %H:%M'),
    }


# ==========================================
# HOVEDFUNKTION
# ==========================================

def main():
    print("\n" + "="*55)
    print("🛰️  ETF SPEJDER — Automatisk Screening")
    print("="*55)

    # Indlæs kendte fonde
    watchlist = load_json(WATCHLIST_FILE, {})
    portfolio = load_json(PORTFOLIO_FILE, {})

    owned_isins     = {isin for isin, p in portfolio.items() if p.get('active', False)}

    # Auto-opdater etf_sold.json når fonde går fra active→inactive i portfolio
    # Salgsdato = i dag, salgskurs = seneste kendte kurs fra etf_latest.json
    sold_funds = load_sold_funds()
    latest_for_sold = load_json(ROOT / "data/etf_latest.json", [])
    latest_sold_map = {item['isin']: item for item in latest_for_sold} if isinstance(latest_for_sold, list) else {}

    newly_sold = 0
    for isin, p in portfolio.items():
        if p.get('active', False):
            # Aktiv fond — fjern fra sold hvis den er der (købt igen)
            if isin in sold_funds:
                del sold_funds[isin]
                print(f"   ✅ {p.get('name', isin)} fjernet fra cool-off (aktiv igen)")
        else:
            # Inaktiv fond — registrér salg hvis ikke allerede i sold
            if isin not in sold_funds:
                item       = latest_sold_map.get(isin, {})
                sold_price = item.get('nav') or p.get('buy_price', 0)
                sold_funds[isin] = {
                    "sold_date":  datetime.now().strftime('%Y-%m-%d'),
                    "sold_price": sold_price,
                    "name":       p.get('name', isin),
                }
                newly_sold += 1
                print(f"   📝 Auto-registreret salg: {p.get('name', isin)} @ {sold_price}")

    if newly_sold > 0 or any(
        isin not in portfolio or not portfolio[isin].get('active', False)
        for isin in list(sold_funds.keys())
        if not isin.startswith('_')
    ):
        save_json(SOLD_FILE, sold_funds)
        print(f"   💾 etf_sold.json opdateret ({len(sold_funds)} fonde i cool-off)")

    # Indlæs Skats ASK-positivliste (5.000+ ISINs — opdateres maj hvert år)
    ask_eligible_isins = load_ask_eligible()

    # Byg ASK-egnethed og depot lookup
    # Prioritet: 1) portfolio (eksplicit sat) 2) watchlist (eksplicit sat) 3) Skats positivliste
    ask_eligible_map = {}
    depot_map        = {}
    for isin, w in watchlist.items():
        if isin.startswith('_'):
            continue
        if w.get('ask_eligible') is not None:
            ask_eligible_map[isin] = w['ask_eligible']
    for isin, p in portfolio.items():
        if p.get('ask_eligible') is not None:
            ask_eligible_map[isin] = p['ask_eligible']
        if p.get('depot'):
            depot_map[isin] = p['depot']
    watchlist_isins = set(watchlist.keys())

    # Indlæs Nordnet-inventory (None = filter deaktiveret)
    nordnet_isins = load_nordnet_inventory()

    # Cool-off filter — sold_funds allerede indlæst og auto-opdateret ovenfor
    if sold_funds:
        print(f"   Cool-off filter: {len(sold_funds)} solgte fonde overvåges")

    # Byg ticker→ISIN mapping fra watchlist
    # justETF returnerer tickers — vi skal matche dem mod ISIN fra portfolio
    ticker_to_isin = {
        v.get('ticker', '').upper(): k
        for k, v in watchlist.items()
        if v.get('ticker')
    }
    # Tilfoej også portfolio tickers
    for isin, p in portfolio.items():
        t = p.get('ticker', '')
        if t:
            ticker_to_isin[t.upper()] = isin

    # Omvendt: ISIN→ticker for owned check
    owned_tickers = {
        p.get('ticker', '').upper()
        for isin, p in portfolio.items()
        if p.get('active', False) and p.get('ticker')
    }

    print(f"📋 Kendte fonde: {len(watchlist_isins)} watchlist, {len(owned_isins)} ejede")
    print(f"   Ticker→ISIN mapping: {len(ticker_to_isin)} tickers kendte")

    # Hent univers
    df = fetch_universe()
    if df is None or len(df) == 0:
        print("❌ Ingen ETF'er at scanne")
        return

    # Konverter til liste af dicts
    # ISIN er DataFrame-index i justetf-scraping — reset_index() gør det til en kolonne
    if df.index.name == 'isin' or (hasattr(df.index, 'name') and str(df.index.name).lower() == 'isin'):
        df = df.reset_index()
    records = df.to_dict('records')

    # Kolonnenavne fra justETF
    # justETF bruger 'ticker' og 'name' — ikke 'isin'
    isin_col   = next((c for c in ['isin', 'ISIN'] if c in df.columns), None)
    ticker_col = next((c for c in ['ticker', 'Ticker'] if c in df.columns), None)
    name_col   = next((c for c in ['name', 'longName', 'shortName', 'title'] if c in df.columns), None)
    year1_col  = next((c for c in ['last_year', 'year1', 'return1year', '1y', 'last_year'] if c in df.columns), None)
    month1_col = next((c for c in ['last_month', 'month1', 'return1month', '1m'] if c in df.columns), None)

    print(f"   Kolonner: isin={isin_col}, ticker={ticker_col}, name={name_col}, 1y={year1_col}, 1m={month1_col}")

    if not ticker_col and not isin_col:
        print(f"❌ Ingen ticker eller ISIN kolonne fundet. Kolonner: {list(df.columns)}")
        return

    print(f"\n🔍 Scanner {len(records)} ETF'er for signaler...")
    print(f"   Bruger ISIN-kolonne: '{isin_col}', Navn-kolonne: '{name_col}'")

    candidates = []
    processed  = 0
    skipped    = 0
    errors     = 0
    nordnet_filtered = 0  # Fonde med signal men ikke på Nordnet

    # -----------------------------------------------------------------------
    # Prioriteret scanning-raekkefoelge
    # 1. Ejede fonde          - scannes altid
    # 2. Watchlist-fonde      - scannes altid
    # 3. Forrige uges top-20  - fastholder gode fonde
    # 4. Resten               - shuffles tilfaeldigt (roterer over uger)
    # -----------------------------------------------------------------------

    # Hent forrige uges hits - max top 20 for at undga voksevaerk
    prev_data_prio = load_json(PREV_HITS_FILE, {})
    prev_hit_tickers = {
        h.get('ticker', '').upper()
        for h in (prev_data_prio.get('hits', []))[:20]
        if h.get('ticker')
    }
    print(f"   Prioriterede fra forrige uge: {len(prev_hit_tickers)} tickers")

    def record_priority(row):
        t = str(row.get(ticker_col, '')).strip().upper() if ticker_col else ''
        for isin_p, p in portfolio.items():
            if p.get('active') and p.get('ticker', '').upper() == t:
                return 0  # ejet
        for isin_w, w in watchlist.items():
            if w.get('ticker', '').upper() == t:
                return 1  # watchlist
        if t in prev_hit_tickers:
            return 2  # forrige uges hit
        return 3  # resten

    # Shuffle resten tilfaeldigt saa universet roterer over tid
    random.shuffle(records)
    # Stabil sort paa prioritet - shuffle bevares inden for gruppe 3
    records.sort(key=record_priority)

    print(f"   Scanning-raekkefoelge: ejede -> watchlist -> prev_hits -> shufflet univers")

    for i, row in enumerate(records):
        isin = str(row.get(isin_col, '')).strip()
        name = str(row.get(name_col, isin)).strip() if name_col else isin


        # Hent ticker direkte fra justETF
        ticker = str(row.get(ticker_col, '')).strip() if ticker_col else ''

        # Konverter til Xetra format hvis nødvendigt
        if ticker and not '.' in ticker:
            ticker = ticker + '.DE'

        # Brug watchlist ticker som override hvis tilgængelig
        if isin and isin in watchlist:
            ticker = watchlist[isin].get('ticker', ticker)

        # Slå ISIN op fra ticker hvis ikke direkte tilgængeligt
        effective_isin = isin or ticker_to_isin.get(ticker.upper(), '')

        is_owned     = (
            (effective_isin in owned_isins) or
            (ticker.upper() in owned_tickers)
        )
        is_watchlist = (
            (effective_isin in watchlist_isins) or
            (ticker.upper() in ticker_to_isin)
        )

        if not ticker:
            skipped += 1
            continue

        # Spring ugyldige justETF placeholder-tickers over ($IBC1.DE, $VZLD.DE osv.)
        # Disse starter med '$' og findes aldrig i yfinance — sparer mange forgæves kald
        if ticker.startswith('$'):
            skipped += 1
            continue

        row['_ticker']         = ticker
        row['_isin']           = effective_isin
        row['_effective_isin'] = effective_isin

        # Hent kurser
        prices = fetch_prices(ticker, months=12)
        if len(prices) < 20:
            skipped += 1
            continue

        time.sleep(YFINANCE_DELAY)

        # Cool-off filter — skip solgte fonde der ikke er vendt til BULL over salgskurs
        # Ejede fonde (is_owned=True) er altid undtaget — de scannes altid
        if not is_owned and is_sold_cooloff(effective_isin, ticker, sold_funds, prices):
            skipped += 1
            continue

        # Score
        result = score_etf(effective_isin, name, row, prices, is_owned, is_watchlist)
        if result:
            # Berig med ASK-info — prioritet: portfolio/watchlist → Skats positivliste
            if effective_isin in ask_eligible_map:
                result['ask_eligible'] = ask_eligible_map[effective_isin]
            elif ask_eligible_isins:
                result['ask_eligible'] = effective_isin in ask_eligible_isins if effective_isin else None
            else:
                result['ask_eligible'] = None
            result['depot']        = depot_map.get(effective_isin, None)
            # Nordnet-filter: efter scoring — vi har nu bekræftet ISIN og kursdata
            # Ejede og watchlist-fonde er altid undtaget
            # Hvis effective_isin er tom kan vi ikke tjekke — lad fonden igennem
            if effective_isin and not is_nordnet_available(effective_isin, nordnet_isins, is_owned, is_watchlist):
                nordnet_filtered += 1
                continue
            candidates.append(result)

        processed += 1

        # Status hvert 25. ETF
        if (i + 1) % 25 == 0:
            print(f"   [{i+1}/{len(records)}] Scannet: {processed}, Kandidater: {len(candidates)}")

        # Stop tidligt hvis vi har nok kandidater og har scannet alle prioriterede
        if len(candidates) >= (MAX_CANDIDATES_STABIL + MAX_CANDIDATES_HURTIG) * 10 and i > 100:
            print(f"   Nok kandidater fundet — stopper tidligt ved {i+1} ETF'er")
            break

    # Indlaes forrige uges hits for at finde NYE fund
    prev_data    = load_json(PREV_HITS_FILE, {})
    prev_tickers = {h.get('ticker', '') for h in prev_data.get('hits_hurtige', [])}

    # Byg lookup af forrige uges momentum per ticker
    prev_momentum_map = {
        h.get('ticker', ''): h.get('momentum', 0)
        for h in prev_data.get('hits', [])
        if h.get('ticker')
    }
    # K1: prev_pile_map — forrige uges momentum-pile per ticker
    # Bruges til consecutive_down detektering (↓↓ to kørsler i træk)
    prev_pile_map = {
        h.get('ticker', ''): h.get('momentum_pile', '—')
        for h in prev_data.get('hits', [])
        if h.get('ticker')
    }


    # Marker nye hurtige heste og beregn momentum-pile
    for c in candidates:
        ticker = c.get('ticker', '')
        c['is_new_this_week'] = (
            c['kategori'] == 'hurtig' and
            ticker not in prev_tickers
        )
        # Momentum-pile: sammenlign denne uges vs forrige uges momentum
        curr_mom = c.get('momentum', 0) or 0
        prev_mom = prev_momentum_map.get(ticker)
        if prev_mom is None:
            # Ikke set forrige uge — kan ikke beregne retning
            c['momentum_pile'] = '—'
        else:
            prev_mom = float(prev_mom) if prev_mom else 0
            if curr_mom > prev_mom:
                c['momentum_pile'] = '↑↑' if prev_mom > 0 else '↓↑'
            else:
                c['momentum_pile'] = '↑↓' if curr_mom > 0 else '↓↓' 

        # K1: consecutive_down — True hvis ↓↓ denne OG forrige kørsel
        # Bruges af etf_send_alert.py til "Momentum svækkes" signal
        curr_pile = c.get('momentum_pile', '—')
        prev_pile = prev_pile_map.get(ticker, '—')
        c['consecutive_down'] = (curr_pile == '↓↓' and prev_pile == '↓↓')

    # Find svageste ejede fond til sammenligning i detaljer
    owned_candidates = [c for c in candidates if c.get('is_owned')]
    if owned_candidates:
        weakest = min(owned_candidates, key=lambda x: x.get('score', 0))
        weakest_info = {'ticker': weakest.get('ticker', ''), 'score': weakest.get('score', 0), 'name': weakest.get('name', '')}
    else:
        weakest_info = None

    # Indlæs history til korrelationsberegning
    history_data = load_json(HISTORY_FILE, {})

    # Tilfoej svageste og portfolio_correlation til alle kandidater
    for c in candidates:
        c['weakest_owned'] = weakest_info
        # Spredningsindikator — kandidatens korrelation mod porteføljen
        if history_data and not c.get('is_owned'):
            corr_val, corr_label, corr_css = build_portfolio_correlation(
                c['isin'], history_data, portfolio, days=90
            )
            c['portfolio_corr']       = corr_val
            c['portfolio_corr_label'] = corr_label
            c['portfolio_corr_css']   = corr_css
        else:
            c['portfolio_corr']       = None
            c['portfolio_corr_label'] = '—'
            c['portfolio_corr_css']   = 'corr-unknown'

    # Del i to kategorier
    stabile = [c for c in candidates if c['kategori'] == 'stabil']
    hurtige  = [c for c in candidates if c['kategori'] == 'hurtig']

    # Sortér hver liste
    stabile.sort(key=lambda x: (x['score'], x.get('weighted_momentum', 0)), reverse=True)
    hurtige.sort(key=lambda x: (x.get('weighted_momentum', 0), x['momentum']), reverse=True)

    top_stabile = stabile[:MAX_CANDIDATES_STABIL]
    top_hurtige  = hurtige[:MAX_CANDIDATES_HURTIG]

    # ── ASK-GARANTI ──────────────────────────────────────────────────────────
    # Sikrer minimum 2 ASK-egnede kort i hver kategori.
    # Swap-logik: hvis under 2 ASK-egnede i top-listen, erstattes de svageste
    # ikke-ASK-egnede kort med de stærkeste ASK-egnede udenfor top-listen.
    # Edge case (B): ingen ASK-egnede kvalificerer til kategoriens momentum-krav
    # → bedste ASK-egnede trækkes ind alligevel med ask_garanteret=True badge.
    ASK_GUARANTEE = 2

    def apply_ask_guarantee(top_list, full_sorted_list, label):
        """
        Sikrer minimum ASK_GUARANTEE ASK-egnede kort i top_list.
        full_sorted_list er den fulde sorterede liste for kategorien.
        Returnerer opdateret top_list.
        """
        ask_count = sum(1 for c in top_list if c.get('ask_eligible') is True)
        if ask_count >= ASK_GUARANTEE:
            return top_list  # Allerede opfyldt

        needed = ASK_GUARANTEE - ask_count

        # Find ASK-egnede kandidater udenfor den nuværende top-liste
        top_isins = {c['isin'] for c in top_list}
        ask_reserve = [
            c for c in full_sorted_list
            if c.get('ask_eligible') is True and c['isin'] not in top_isins
        ]

        # Hvis der ikke er nok i reserve — søg i ALLE kandidater på tværs
        # (edge case B: momentum-kategori har for få ASK-egnede)
        if len(ask_reserve) < needed:
            all_isins_in_top = top_isins
            ask_reserve_all = [
                c for c in candidates
                if c.get('ask_eligible') is True and c['isin'] not in all_isins_in_top
            ]
            # Sortér på momentum så vi får de stærkeste
            ask_reserve_all.sort(key=lambda x: x.get('momentum', 0), reverse=True)
            # Fyld op fra den brede reserve
            extra_isins = {c['isin'] for c in ask_reserve}
            for c in ask_reserve_all:
                if c['isin'] not in extra_isins:
                    ask_reserve.append(c)
                    extra_isins.add(c['isin'])

        swapped = 0
        new_top = list(top_list)
        for candidate in ask_reserve:
            if swapped >= needed:
                break
            # Find svageste ikke-ASK-egnede i bunden af listen og swap
            swap_idx = None
            for i in range(len(new_top) - 1, -1, -1):
                if new_top[i].get('ask_eligible') is not True:
                    swap_idx = i
                    break
            if swap_idx is not None:
                # Normal swap — kandidaten er fra samme kategori
                new_top[swap_idx] = candidate
            else:
                # Alle pladser er allerede ASK-egnede — tilføj ekstra
                new_top.append(candidate)

            # Marker som ASK-garanteret hvis den ikke opfylder kategoriens
            # normale momentum-krav (edge case B)
            if label == 'hurtig' and candidate.get('momentum', 0) < HURTIG_MIN_MOMENTUM:
                candidate['ask_garanteret'] = True
            elif label == 'stabil' and (
                candidate.get('momentum', 0) < MIN_MOMENTUM_PCT or
                (candidate.get('rsi') or 0) >= MAX_RSI
            ):
                candidate['ask_garanteret'] = True
            else:
                candidate['ask_garanteret'] = False

            swapped += 1
            print(f"   🔒 ASK-garanti ({label}): {candidate.get('ticker', candidate['isin'])} swappet ind"
                  f"{' [ASK-garanti badge]' if candidate.get('ask_garanteret') else ''}")

        return new_top

    top_hurtige = apply_ask_guarantee(top_hurtige, hurtige, 'hurtig')
    top_stabile = apply_ask_guarantee(top_stabile, stabile, 'stabil')
    # ── SLUT ASK-GARANTI ─────────────────────────────────────────────────────

    top_alle     = top_hurtige + top_stabile  # Hurtige øverst

    # Gem hits
    output = {
        "_scanned_at":    datetime.now().strftime('%Y-%m-%d %H:%M'),
        "_total_scanned": processed,
        "_total_hits":    len(candidates),
        "_stabile_hits":  len(stabile),
        "_hurtige_hits":  len(hurtige),
        "_filters": {
            "min_aum_eur":         MIN_AUM_EUR,
            "max_ter":             MAX_TER,
            "min_momentum_stabil": MIN_MOMENTUM_PCT,
            "max_rsi_stabil":      MAX_RSI,
            "min_momentum_hurtig": HURTIG_MIN_MOMENTUM,
            "min_1y_hurtig":       HURTIG_MIN_1Y,
            "min_score":           MIN_SCORE,
            "nordnet_filter":      nordnet_isins is not None,
            "nordnet_inventory_size": len(nordnet_isins) if nordnet_isins else 0,
        },
        "hits":         top_alle,
        "hits_stabile": top_stabile,
        "hits_hurtige": top_hurtige,
        "hits_nye":     [h for h in top_hurtige if h.get('is_new_this_week', False)],
    }

    # Gem nuvaerende hits som "forrige uge" til naeste kørsel
    if HITS_FILE.exists():
        import shutil
        shutil.copy(HITS_FILE, PREV_HITS_FILE)

    save_json(HITS_FILE, output)

    print(f"\n{'='*55}")
    print(f"✅ Spejder færdig")
    print(f"   Scannet: {processed} ETF'er")
    print(f"   Sprunget over: {skipped} (ingen ticker/kursdata)")
    print(f"   Nordnet-filter: {'✅ Aktiv (' + str(len(nordnet_isins)) + ' ISINs)' if nordnet_isins else '⚠️  Deaktiveret (fil mangler)'}")
    print(f"   Nordnet-afvist (signal men ikke handlbar): {nordnet_filtered}")
    print(f"   Kandidater: {len(candidates)}")
    print(f"   Top {len(top_hurtige) + len(top_stabile)} gemt til {HITS_FILE.name}")
    print()

    if top_hurtige:
        print(f"\n🚀 Hurtige Heste ({len(top_hurtige)}):")
        for h in top_hurtige[:5]:
            owned_tag = " ⭐" if h['is_owned'] else ""
            print(f"  [{h['score']}pt] {h['name'][:40]}{owned_tag}")
            hist_warn = " ⚠️ kort historik" if h.get('short_history') else ""
            print(f"       Momentum: +{h['momentum']}%, RSI: {h['rsi']}, 1Y: {h['return_1y']}%{hist_warn}")

    if top_stabile:
        print(f"\n📈 Stabile Trendere ({len(top_stabile)}):")
        for h in top_stabile[:5]:
            owned_tag = " ⭐" if h['is_owned'] else ""
            print(f"  [{h['score']}pt] {h['name'][:40]}{owned_tag}")
            hist_warn = " ⚠️ kort historik" if h.get('short_history') else ""
            print(f"       Momentum: +{h['momentum']}%, RSI: {h['rsi']}, 1Y: {h['return_1y']}%{hist_warn}")

    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
