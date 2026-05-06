"""
etf_provider.py — Datahentning for TrendAgent ETF-system
=========================================================
Henter daglige kurser for alle ETF'er i config/etf_watchlist.json
via yfinance og opdaterer:
  - data/etf_history.json  (daglige kurser per ISIN)
  - data/etf_latest.json   (seneste kurs + beregnede afkasttal)

Køres dagligt af .github/workflows/etf_daily.yml
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Tilføj reporting/ til Python-stien så utils.py kan importeres
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import get_volatility

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance ikke installeret. Kør: pip install yfinance")
    sys.exit(1)

# ==========================================
# STIER
# ==========================================
ROOT           = Path(__file__).resolve().parents[1]
WATCHLIST_FILE = ROOT / "config/etf_watchlist.json"
HISTORY_FILE   = ROOT / "data/etf_history.json"
LATEST_FILE    = ROOT / "data/etf_latest.json"

# Maksimalt tilladt dagligt kursspring i % før datapunktet afvises.
# ETF'er kan være volatile — sat til 25% for at dække ekstreme dage
# uden at fange parser-fejl.
VOLATILITY_GUARD_PCT = 0.25

# Hvor mange års historik vi henter første gang (bootstrapping)
INITIAL_HISTORY_YEARS = 2


# ==========================================
# FIL-HJÆLPEFUNKTIONER
# ==========================================

def load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Kunne ikke læse {path}: {e}")
        return default

def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ==========================================
# AFKAST-BEREGNING FRA HISTORIK
# ==========================================

def calculate_return(prices_dict, days):
    """
    Beregner afkast over 'days' kalenderdage fra historikken.
    Finder nærmeste tilgængelige dato som startpunkt.
    Returnerer procent eller None hvis ikke nok data.
    """
    if not prices_dict:
        return None

    dates = sorted(prices_dict.keys())
    if not dates:
        return None

    latest_date = datetime.strptime(dates[-1], '%Y-%m-%d')
    target_date = latest_date - timedelta(days=days)

    # Find nærmeste dato der er <= target_date
    candidates = [d for d in dates if datetime.strptime(d, '%Y-%m-%d') <= target_date]
    if not candidates:
        return None

    start_price = prices_dict[candidates[-1]]
    end_price   = prices_dict[dates[-1]]

    if not start_price or start_price == 0:
        return None

    return round(((end_price / start_price) - 1) * 100, 2)


def calculate_ytd(prices_dict):
    """Beregner afkast siden 31. december forrige år."""
    if not prices_dict:
        return None

    dates = sorted(prices_dict.keys())
    cur_year = datetime.now().year

    # Find seneste kurs fra forrige år
    prev_year_dates = [d for d in dates if d < f"{cur_year}-01-01"]
    if not prev_year_dates:
        # Fallback: første kurs i år
        this_year_dates = [d for d in dates if d.startswith(str(cur_year))]
        if not this_year_dates:
            return None
        start_price = prices_dict[this_year_dates[0]]
    else:
        start_price = prices_dict[prev_year_dates[-1]]

    if not start_price or start_price == 0:
        return None

    end_price = prices_dict[dates[-1]]
    return round(((end_price / start_price) - 1) * 100, 2)


# ==========================================
# YFINANCE DATA-HENTNING
# ==========================================

def fetch_history(ticker, existing_dates):
    """
    Henter kurshistorik via yfinance.

    Hvis fonden er ny i systemet: henter INITIAL_HISTORY_YEARS år bagud.
    Ellers: henter kun de seneste 5 dage (effektivt daglig opdatering).

    Returnerer dict: { 'YYYY-MM-DD': kurs } eller {} ved fejl.
    """
    try:
        t = yf.Ticker(ticker)

        if not existing_dates:
            # Første gang — hent fuld historik
            period = f"{INITIAL_HISTORY_YEARS}y"
            print(f"  [BOOTSTRAP] {ticker}: henter {INITIAL_HISTORY_YEARS} års historik...")
        else:
            # Daglig opdatering — hent kun de seneste dage
            period = "5d"

        hist = t.history(period=period, auto_adjust=True)

        if hist.empty:
            print(f"  ⚠️  {ticker}: ingen data fra yfinance")
            return {}

        result = {}
        for date, row in hist.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            close    = round(float(row['Close']), 4)
            if close > 0:
                result[date_str] = close

        return result

    except Exception as e:
        print(f"  ❌ {ticker}: fejl ved datahentning — {e}")
        return {}


# ==========================================
# VOLATILITY GUARD
# ==========================================

def check_volatility(ticker, new_price, new_date, existing_dict):
    """
    Tjekker om et nyt datapunkt er realistisk ift. eksisterende historik.
    Returnerer True hvis datapunktet skal gemmes, False hvis det afvises.
    """
    if not existing_dict:
        return True

    # Find seneste eksisterende kurs inden for 10 dage
    target = datetime.strptime(new_date, '%Y-%m-%d') - timedelta(days=10)
    recent = {
        d: v for d, v in existing_dict.items()
        if datetime.strptime(d, '%Y-%m-%d') >= target
        and d < new_date
    }

    if not recent:
        return True

    last_date  = max(recent.keys())
    last_price = recent[last_date]

    diff = abs((new_price - last_price) / last_price)
    if diff > VOLATILITY_GUARD_PCT:
        print(
            f"  ⚠️  Volatility Guard: {ticker} afvist: "
            f"{last_price} → {new_price} ({diff*100:.1f}%) "
            f"på {last_date} → {new_date}"
        )
        return False

    return True


# ==========================================
# HOVEDFUNKTION
# ==========================================

def main():
    print("\n" + "="*50)
    print("📡 ETF PROVIDER — Datahentning")
    print("="*50)

    # Indlæs watchlist
    watchlist_raw = load_json(WATCHLIST_FILE, {})
    watchlist = {
        isin: data for isin, data in watchlist_raw.items()
        if not isin.startswith('_')  # Spring kommentar-felter over
    }

    if not watchlist:
        print(f"❌ Watchlist mangler eller er tom: {WATCHLIST_FILE}")
        return

    print(f"📋 Watchlist: {len(watchlist)} ETF'er")

    # Indlæs eksisterende historik
    history = load_json(HISTORY_FILE, {})
    today   = datetime.now().strftime('%Y-%m-%d')

    new_points   = 0
    failed       = 0
    latest_list  = []

    for isin, etf_info in watchlist.items():
        ticker = etf_info.get('ticker')
        name   = etf_info.get('name', isin)

        if not ticker:
            print(f"  ⚠️  {isin}: ingen ticker defineret — springes over")
            failed += 1
            continue

        print(f"\n  {ticker} ({name[:40]})")

        # Eksisterende historik for denne ETF
        existing = history.get(isin, {})

        # Hent nye kurser fra yfinance
        new_prices = fetch_history(ticker, existing)

        if not new_prices:
            failed += 1
            # Brug eksisterende data hvis tilgængeligt
            if existing:
                dates      = sorted(existing.keys())
                last_price = existing[dates[-1]]
                last_date  = dates[-1]
            else:
                print(f"  ❌ {ticker}: ingen data overhovedet")
                continue
        else:
            # Tilføj nye datapunkter med volatility guard
            added = 0
            for date_str, price in sorted(new_prices.items()):
                if date_str in existing:
                    continue  # Overskriv aldrig eksisterende data
                if check_volatility(ticker, price, date_str, existing):
                    existing[date_str] = price
                    added += 1
                    new_points += 1

            if added > 0:
                print(f"  ✅ {added} nye datapunkter tilføjet")

            # Sorter datoer
            existing   = dict(sorted(existing.items()))
            dates      = list(existing.keys())
            last_price = existing[dates[-1]]
            last_date  = dates[-1]

        # Gem opdateret historik
        history[isin] = existing

        # Beregn volatilitet (20-dages standardafvigelse af daglige afkast)
        prices_list = [existing[d] for d in sorted(existing.keys())]
        volatility  = get_volatility(prices_list, 20)

        # Beregn afkasttal fra historik
        return_1w  = calculate_return(existing, 7)
        return_1m  = calculate_return(existing, 30)
        return_3m  = calculate_return(existing, 91)
        return_6m  = calculate_return(existing, 182)
        return_1y  = calculate_return(existing, 365)
        return_ytd = calculate_ytd(existing)

        print(f"  📊 1W: {return_1w}%  1M: {return_1m}%  1Y: {return_1y}%  ÅTD: {return_ytd}%")

        # Byg latest-entry
        latest_list.append({
            "isin":        isin,
            "name":        name,
            "ticker":      ticker,
            "category":    etf_info.get('category', ''),
            "ter_pct":     etf_info.get('ter_pct'),
            "nav":         last_price,
            "nav_date":    last_date,
            "currency":    "EUR",   # Alle Xetra ETF'er handles i EUR
            "return_1w":   return_1w,
            "return_1m":   return_1m,
            "return_3m":   return_3m,
            "return_6m":   return_6m,
            "return_1y":   return_1y,
            "return_ytd":  return_ytd,
            "volatility":  volatility,
            "data_points": len(existing),
        })

    # Gem filer
    save_json(HISTORY_FILE, history)
    save_json(LATEST_FILE,  latest_list)

    print(f"\n{'='*50}")
    print(f"✅ ETF Provider færdig")
    print(f"   {len(latest_list)} ETF'er behandlet")
    print(f"   {new_points} nye datapunkter tilføjet")
    if failed:
        print(f"   ⚠️  {failed} ETF'er fejlede")
    print(f"   Gemt: {LATEST_FILE.name}, {HISTORY_FILE.name}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
