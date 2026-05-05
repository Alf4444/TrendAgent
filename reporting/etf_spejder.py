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

# ==========================================
# KONFIGURATION
# ==========================================
ROOT             = Path(__file__).resolve().parents[1]
WATCHLIST_FILE   = ROOT / "config/etf_watchlist.json"
PORTFOLIO_FILE   = ROOT / "config/etf_portfolio.json"
HITS_FILE        = ROOT / "data/etf_spejder_hits.json"

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

    if score < MIN_SCORE:
        return None

    # Bestem kategori
    return_1y_val = round(float(return_1y_raw), 2) if return_1y_raw is not None else 0
    if momentum >= HURTIG_MIN_MOMENTUM or return_1y_val >= HURTIG_MIN_1Y:
        kategori = "hurtig"
    else:
        kategori = "stabil"

    return {
        "isin":        isin,
        "name":        name,
        "ticker":      row.get('_ticker', ''),
        "score":       score,
        "kategori":    kategori,
        "momentum":    momentum,
        "ma_label":    ma_label,
        "trend":       trend,
        "rsi":         round(rsi, 1) if rsi else None,
        "cross":       cross,
        "return_1m":   round(return_1m, 2) if return_1m is not None else None,
        "return_1y":   return_1y_val if return_1y_raw is not None else None,
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
    watchlist_isins = set(watchlist.keys())

    print(f"📋 Kendte fonde: {len(watchlist_isins)} watchlist, {len(owned_isins)} ejede")

    # Hent univers
    df = fetch_universe()
    if df is None or len(df) == 0:
        print("❌ Ingen ETF'er at scanne")
        return

    # Konverter til liste af dicts
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

    # Sorter: ejede og watchlist-fonde scannes altid
    # Resten sorteres på 1Y afkast så vi scanner de stærkeste først
    year1_col = next((c for c in ['year1', 'return1year', '1y'] if c in df.columns), None)
    if year1_col:
        try:
            records = sorted(records, key=lambda x: float(x.get(year1_col) or 0), reverse=True)
        except Exception:
            pass

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

        is_owned     = (isin in owned_isins) if isin else False
        is_watchlist = (isin in watchlist_isins) if isin else (ticker.replace('.DE','') in {w.get('ticker','').replace('.DE','') for w in watchlist.values()})

        if not ticker:
            skipped += 1
            continue

        row['_ticker'] = ticker
        row['_isin']   = isin or ticker

        # Hent kurser
        prices = fetch_prices(ticker, months=12)
        if len(prices) < 20:
            skipped += 1
            continue

        time.sleep(YFINANCE_DELAY)

        # Score
        effective_isin = isin or row.get('_isin', ticker)
        result = score_etf(effective_isin, name, row, prices, is_owned, is_watchlist)
        if result:
            candidates.append(result)

        processed += 1

        # Status hvert 25. ETF
        if (i + 1) % 25 == 0:
            print(f"   [{i+1}/{len(records)}] Scannet: {processed}, Kandidater: {len(candidates)}")

        # Stop tidligt hvis vi har nok kandidater og har scannet alle prioriterede
        if len(candidates) >= (MAX_CANDIDATES_STABIL + MAX_CANDIDATES_HURTIG) * 3 and i > 100:
            print(f"   Nok kandidater fundet — stopper tidligt ved {i+1} ETF'er")
            break

    # Del i to kategorier
    stabile = [c for c in candidates if c['kategori'] == 'stabil']
    hurtige  = [c for c in candidates if c['kategori'] == 'hurtig']

    # Sortér hver liste
    stabile.sort(key=lambda x: (x['score'], x['momentum']), reverse=True)
    hurtige.sort(key=lambda x: x['momentum'], reverse=True)

    top_stabile = stabile[:MAX_CANDIDATES_STABIL]
    top_hurtige  = hurtige[:MAX_CANDIDATES_HURTIG]
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
        },
        "hits":         top_alle,
        "hits_stabile": top_stabile,
        "hits_hurtige": top_hurtige,
    }

    save_json(HITS_FILE, output)

    print(f"\n{'='*55}")
    print(f"✅ Spejder færdig")
    print(f"   Scannet: {processed} ETF'er")
    print(f"   Sprunget over: {skipped} (ingen ticker)")
    print(f"   Kandidater: {len(candidates)}")
    print(f"   Top {len(top_hurtige) + len(top_stabile)} gemt til {HITS_FILE.name}")
    print()

    if top_hurtige:
        print(f"\n🚀 Hurtige Heste ({len(top_hurtige)}):")
        for h in top_hurtige[:5]:
            owned_tag = " ⭐" if h['is_owned'] else ""
            print(f"  [{h['score']}pt] {h['name'][:40]}{owned_tag}")
            print(f"       Momentum: +{h['momentum']}%, RSI: {h['rsi']}, 1Y: {h['return_1y']}%")

    if top_stabile:
        print(f"\n📈 Stabile Trendere ({len(top_stabile)}):")
        for h in top_stabile[:5]:
            owned_tag = " ⭐" if h['is_owned'] else ""
            print(f"  [{h['score']}pt] {h['name'][:40]}{owned_tag}")
            print(f"       Momentum: +{h['momentum']}%, RSI: {h['rsi']}, 1Y: {h['return_1y']}%")

    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
