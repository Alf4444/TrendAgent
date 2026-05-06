"""
etf_build_monthly.py — Månedlig ETF-rapport for TrendAgent
============================================================
Genererer build/etf_monthly.html med:
  - Aktive positioner med total afkast, rank og Trend Velocity
  - Alpha vs benchmark (VVSM som proxy for globalt ETF-marked)
  - Top 5 markedsmuligheder fra watchlist
  - Trail Stop advarsler
  - Strategiske handlingssignaler

Køres af .github/workflows/etf_monthly.yml (lørdag kl. 07:30)
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from jinja2 import Template

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    get_ma, get_best_ma, get_rsi,
    get_trend_velocity, get_momentum_status,
    get_trend_state, get_trend_shift,
    check_trail_stop, is_trading_day,
)

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT           = Path(__file__).resolve().parents[1]
LATEST_FILE    = ROOT / "data/etf_latest.json"
HISTORY_FILE   = ROOT / "data/etf_history.json"
WATCHLIST_FILE = ROOT / "config/etf_watchlist.json"
PORTFOLIO_FILE = ROOT / "config/etf_portfolio.json"
HWM_FILE       = ROOT / "data/etf_hwm.json"
TEMPLATE_FILE  = ROOT / "templates/etf_monthly.html.j2"
REPORT_FILE    = ROOT / "build/etf_monthly.html"

TRAIL_STOP_PCT = 3.0  # Default — overrides af volatilitet per fond

def get_trail_stop_pct(volatility):
    """
    Beregner variabelt Trail Stop baseret på fondens volatilitet.
    Høj volatilitet = løsere stop (undgår falske alarmer).
    Lav volatilitet = strammere stop (beskytter gevinster tæt).

    Volatilitet er 20-dages standardafvigelse af daglige afkast i %.
      < 1.0%  → 3% stop  (fx obligationer, lav-vol fonde)
      1-2%    → 5% stop  (fx brede aktieindeks)
      > 2.0%  → 7% stop  (fx Korea, Hydrogen, Halvledere)
    """
    if volatility is None:
        return TRAIL_STOP_PCT
    if volatility < 1.0:
        return 3.0
    elif volatility < 2.0:
        return 5.0
    else:
        return 7.0

# Benchmark — iShares Core MSCI World UCITS ETF bruges som bredt markedsbenchmark
# Ticker: IWDA.AS (Amsterdam) — repræsenterer globalt udviklede markeder
BENCHMARK_ISIN = "IE00B4L5Y983"  # IWDA — iShares Core MSCI World


# ==========================================
# HJÆLPEFUNKTIONER
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

def load_hwm():
    if HWM_FILE.exists():
        try:
            with open(HWM_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_hwm(hwm_data):
    HWM_FILE.parent.mkdir(exist_ok=True)
    with open(HWM_FILE, "w", encoding="utf-8") as f:
        json.dump(hwm_data, f, indent=2)

def get_ranking_data(latest_list):
    """Rangerer alle ETF'er efter 1M afkast."""
    sorted_list = sorted(latest_list, key=lambda x: x.get('return_1m') or -999, reverse=True)
    rank_map = {item['isin']: index + 1 for index, item in enumerate(sorted_list)}
    return rank_map, len(sorted_list)


# ==========================================
# HOVEDFUNKTION
# ==========================================

def build_monthly():
    print("🔄 Starter generering af ETF månedlig rapport...")

    for f in [LATEST_FILE, HISTORY_FILE, WATCHLIST_FILE, TEMPLATE_FILE]:
        if not f.exists():
            print(f"❌ FEJL: Mangler fil: {f}")
            return

    latest    = load_json(LATEST_FILE, [])
    history   = load_json(HISTORY_FILE, {})
    watchlist = load_json(WATCHLIST_FILE, {})
    portfolio = load_json(PORTFOLIO_FILE, {})
    watchlist = {k: v for k, v in watchlist.items() if not k.startswith('_')}
    portfolio = {k: v for k, v in portfolio.items() if not k.startswith('_')}
    # Benchmark-fonde må ikke vises i tabeller eller markedsmuligheder
    benchmark_isins = {k for k, v in watchlist.items() if v.get('_benchmark')}

    rank_map, total_count = get_ranking_data(latest)
    latest_map = {item['isin']: item for item in latest}

    now         = datetime.now()
    today_str   = now.strftime('%Y-%m-%d')
    timestamp   = now.strftime('%d-%m-%Y %H:%M')
    week_number = now.strftime('%V')

    hwm_data          = load_hwm()
    trail_stop_alerts = []
    active_rows       = []
    sold_rows         = []
    active_returns    = []

    for isin, p_info in portfolio.items():
        if isin not in latest_map:
            continue

        official  = latest_map[isin]
        rank      = rank_map.get(isin, 99)
        curr_p    = official.get('nav') or 0
        buy_p     = p_info.get('buy_price', 0)
        is_active = p_info.get('active', False)

        total_return = round(((curr_p - buy_p) / buy_p * 100), 2) if buy_p > 0 else 0

        # Historik — kun handelsdage
        p_dict = history.get(isin, {})
        sorted_dates = [d for d in sorted(p_dict.keys()) if is_trading_day(d)]
        prices = [p_dict[d] for d in sorted_dates]
        if not prices or prices[-1] != curr_p:
            prices.append(curr_p)

        rsi_val          = get_rsi(prices, 14)
        ma_val, ma_label = get_best_ma(prices)

        # Trend Velocity og Momentum Status
        t_label, t_class = get_trend_velocity(
            official.get('return_1w') or 0,
            official.get('return_1m') or 0,
        )
        m_label, m_class = get_momentum_status(
            official.get('return_1m') or 0,
            rank,
        )

        # Trend state + shift
        prev_trend  = hwm_data.get(isin, {}).get('trend_state')
        t_state     = get_trend_state(prices)
        trend_shift = get_trend_shift(prices, prev_trend)

        if isin in hwm_data:
            hwm_data[isin]['trend_state'] = t_state
        else:
            hwm_data[isin] = {'trend_state': t_state}

        fund_data = {
            "isin":           isin,
            "name":           p_info.get('name', isin),
            "ticker":         p_info.get('ticker', official.get('ticker', '')),
            "category":       watchlist.get(isin, {}).get('category', ''),
            "rank":           rank,
            "buy_date":       p_info.get('buy_date', 'N/A'),
            "buy_price":      buy_p,
            "curr_price":     curr_p,
            "return_1w":      official.get('return_1w') or 0,
            "return_1m":      official.get('return_1m') or 0,
            "return_ytd":     official.get('return_ytd'),
            "return_1y":      official.get('return_1y'),
            "trend_label":    t_label,
            "trend_class":    t_class,
            "momentum_label": m_label,
            "momentum_class": m_class,
            "total_return":   total_return,
            "rsi":            rsi_val,
            "ma":             ma_val,
            "ma_label":       ma_label,
            "t_state":        t_state,
            "trend_shift":    trend_shift,
            "is_active":      is_active,
        }

        if is_active:
            active_rows.append(fund_data)
            active_returns.append(total_return)

            # Trail Stop
            hwm_entry, alert = check_trail_stop(
                isin, curr_p, buy_p, hwm_data, today_str,
                get_trail_stop_pct(official.get('volatility'))
            )
            hwm_data[isin] = hwm_entry
            if alert:
                alert["name"] = p_info.get('name', isin)
                trail_stop_alerts.append(alert)
                print(f"🔔 TRAIL STOP: {alert['name']} faldet {alert['fall_pct']}% fra top")
        else:
            fund_data["sell_date"]  = p_info.get('sell_date', 'N/A')
            fund_data["sell_price"] = p_info.get('sell_price', 'N/A')
            sold_rows.append(fund_data)

    save_hwm(hwm_data)

    # --- BENCHMARK ---
    benchmark_item   = latest_map.get(BENCHMARK_ISIN, {})
    benchmark_return = benchmark_item.get('return_1m') or 0
    benchmark_name   = benchmark_item.get('name', 'iShares Core MSCI World')
    # Fallback: hvis IWDA ikke er i universet, brug porteføljens egne afkast som reference
    if not benchmark_item:
        print("⚠️  MSCI World benchmark (IWDA) ikke fundet i etf_latest.json — benchmark vises som N/A")
        benchmark_name = "MSCI World (ikke tilgængeligt)"

    avg_port_return = (
        sum(active_returns) / len(active_returns)
        if active_returns else 0
    )

    # --- TOP 5 MARKEDSMULIGHEDER ---
    # Ikke-ejede ETF'er sorteret efter 1M afkast
    # Ekskluderer ALLE positioner i portfolio (aktive + solgte)
    all_portfolio_isins = set(portfolio.keys())
    opps = [
        item for item in latest
        if item['isin'] not in all_portfolio_isins
        and item['isin'] not in benchmark_isins
        and item.get('return_1m') is not None
    ]
    opps_sorted = sorted(opps, key=lambda x: x.get('return_1m') or 0, reverse=True)[:5]

    market_opps = []
    for o in opps_sorted:
        t_label_o, _ = get_trend_velocity(
            o.get('return_1w') or 0,
            o.get('return_1m') or 0,
        )
        market_opps.append({
            "name":        o.get('name', o['isin']),
            "ticker":      o.get('ticker', ''),
            "category":    watchlist.get(o['isin'], {}).get('category', ''),
            "return_1m":   o.get('return_1m') or 0,
            "return_ytd":  o.get('return_ytd') or 0,
            "return_1y":   o.get('return_1y'),
            "rank":        rank_map.get(o['isin']),
            "trend_label": t_label_o,
        })

    # Handlingssignaler
    sell_signals = [f for f in active_rows if f['momentum_class'] == 'momentum-flat']
    buy_signals  = [o for o in market_opps if o['return_1m'] > 10.0]

    if not TEMPLATE_FILE.exists():
        print(f"❌ Template mangler: {TEMPLATE_FILE}")
        return

    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html = template.render(
        timestamp            = timestamp,
        week_number          = week_number,
        active_funds         = sorted(active_rows, key=lambda x: x['rank']),
        sold_funds           = sold_rows,
        market_opps          = market_opps,
        sell_signals         = sell_signals,
        buy_signals          = buy_signals,
        trail_stop_alerts    = trail_stop_alerts,
        benchmark_name       = benchmark_name,
        benchmark_return     = round(benchmark_return, 2),
        avg_portfolio_return = round(avg_port_return, 2),
        diff_to_benchmark    = round(avg_port_return - benchmark_return, 2),
        total_count          = total_count,
        trail_stop_pct       = TRAIL_STOP_PCT,
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html, encoding="utf-8")
    print(f"✅ ETF Månedlig rapport færdig (Uge {week_number})")
    if trail_stop_alerts:
        print(f"   ⚠️  {len(trail_stop_alerts)} trail stop-advarsel(er)")


if __name__ == "__main__":
    build_monthly()
