"""
etf_build_weekly.py — Ugentlig ETF-rapport for TrendAgent
==========================================================
Genererer build/etf_weekly.html med:
  - Aktive ETF-positioner med Trail Stop og afkast
  - Spejderens top-kandidater (momentum + Golden Cross)
  - Top 5 op/ned i universet
  - Momentum-chart over alle ETF'er

Køres af .github/workflows/etf_weekly.yml (lørdag kl. 07:00)
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# Tilføj reporting/ til Python-stien så utils.py kan importeres
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    get_ma, get_best_ma, get_rsi,
    calculate_drawdown, calculate_ytd,
    get_cross_signal, get_trend_state,
    check_trail_stop, is_trading_day,
)
from sector_heatmap import build_heatmap, get_concentration_warning

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT           = Path(__file__).resolve().parents[1]
LATEST_FILE    = ROOT / "data/etf_latest.json"
HISTORY_FILE   = ROOT / "data/etf_history.json"
WATCHLIST_FILE = ROOT / "config/etf_watchlist.json"
PORTFOLIO_FILE = ROOT / "config/etf_portfolio.json"
HWM_FILE       = ROOT / "data/etf_hwm.json"
SPEJDER_FILE   = ROOT / "data/etf_spejder_hits.json"
TEMPLATE_FILE  = ROOT / "templates/etf_weekly.html.j2"
REPORT_FILE    = ROOT / "build/etf_weekly.html"

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

# Spejder-filtre


# ==========================================
# HWM — fil-håndtering
# ==========================================

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


# ==========================================
# HOVEDFUNKTION
# ==========================================

def build_weekly():
    print("🔄 Starter generering af ETF ugerapport...")

    for f in [LATEST_FILE, HISTORY_FILE, WATCHLIST_FILE, TEMPLATE_FILE]:
        if not f.exists():
            print(f"❌ FEJL: Mangler fil: {f}")
            return

    latest    = load_json(LATEST_FILE, [])
    history   = load_json(HISTORY_FILE, {})
    watchlist = load_json(WATCHLIST_FILE, {})
    portfolio = load_json(PORTFOLIO_FILE, {})

    watchlist = {k: v for k, v in watchlist.items() if not k.startswith('_')}
    # Benchmark-fonde må ikke vises i tabeller, top/bund eller Spejder
    benchmark_isins = {k for k, v in watchlist.items() if v.get('_benchmark')}

    portfolio_isins = {
        isin for isin, info in portfolio.items()
        if info.get("active", False)
    }

    hwm_data          = load_hwm()

    # Indlæs Spejder-hits hvis tilgængelige
    spejder_data     = load_json(SPEJDER_FILE, {})
    spejder_hits_all = spejder_data.get('hits', [])         if isinstance(spejder_data, dict) else []
    spejder_hurtige  = spejder_data.get('hits_hurtige', []) if isinstance(spejder_data, dict) else []
    spejder_stabile  = spejder_data.get('hits_stabile', []) if isinstance(spejder_data, dict) else []
    spejder_meta = {
        'scanned_at':    spejder_data.get('_scanned_at', ''),
        'total_scanned': spejder_data.get('_total_scanned', 0),
        'total_hits':    spejder_data.get('_total_hits', 0),
        'hurtige_hits':  spejder_data.get('_hurtige_hits', 0),
        'stabile_hits':  spejder_data.get('_stabile_hits', 0),
    } if spejder_data else {}
    today_str         = datetime.now().strftime('%Y-%m-%d')
    trail_stop_alerts = []

    rows              = []
    active_week_returns = []
    spejder_hits      = []

    for item in latest:
        isin      = item['isin']
        # Spring benchmark-fonde over — de må ikke vises i tabellen
        if isin in benchmark_isins:
            continue
        p_dict    = history.get(isin, {})

        # Kun handelsdage
        sorted_dates = [d for d in sorted(p_dict.keys()) if is_trading_day(d)]
        p_list       = [p_dict[d] for d in sorted_dates]

        if not p_list:
            continue

        cur_nav   = item.get('nav') or 0.0
        is_active = isin in portfolio_isins

        # Sikr dagens NAV er med
        if p_list[-1] != cur_nav:
            p_list.append(cur_nav)

        # --- TEKNISKE BEREGNINGER ---
        ma_val, ma_label = get_best_ma(p_list)
        rsi              = get_rsi(p_list, 14)
        cross            = get_cross_signal(p_list)
        dd               = calculate_drawdown(p_list)

        # Momentum — afstand til bedste MA
        if ma_val and cur_nav:
            momentum = round(((cur_nav / ma_val) - 1) * 100, 2)
        else:
            momentum = round(item.get('return_1m') or 0.0, 2)
            ma_label = "1M proxy"

        trend_state = get_trend_state(p_list)

        # RSI alert
        rsi_alert = None
        if rsi is not None:
            if rsi >= 70:
                rsi_alert = "overkøbt"
            elif rsi <= 30:
                rsi_alert = "oversolgt"

        # Afkast
        week_change = float(item.get('return_1w') or 0.0)
        if is_active and isin in portfolio:
            buy_price = portfolio[isin].get('buy_price', 0)
            total_ret = round(((cur_nav / buy_price) - 1) * 100, 2) if buy_price else 0.0
        else:
            buy_price = 0
            total_ret = round(((cur_nav / p_list[0]) - 1) * 100, 2) if p_list else 0.0

        if is_active:
            active_week_returns.append(week_change)

        # --- TRAIL STOP (kun aktive) ---
        trail_alert = None
        if is_active and buy_price and cur_nav:
            etf_vol    = item.get('volatility') if 'item' in dir() else None
            trail_pct  = get_trail_stop_pct(etf_vol)
            hwm_entry, trail_alert = check_trail_stop(
                isin, cur_nav, buy_price, hwm_data, today_str, trail_pct
            )
            hwm_data[isin] = hwm_entry
            if trail_alert:
                trail_alert["name"] = portfolio[isin].get("name", item.get('name', isin))
                trail_stop_alerts.append(trail_alert)
                print(
                    f"🔔 TRAIL STOP: {trail_alert['name']} faldet {trail_alert['fall_pct']}% "
                    f"fra top {trail_alert['hwm']} → nu {trail_alert['curr']}"
                )

        row = {
            'isin':            isin,
            'name':            item.get('name', isin),
            'ticker':          item.get('ticker', ''),
            'category':        item.get('category', ''),
            'week_change_pct': week_change,
            'total_return':    float(total_ret),
            'trend_state':     trend_state,
            'ma_label':        ma_label,
            'momentum':        momentum,
            'rsi':             rsi,
            'rsi_alert':       rsi_alert,
            'cross_20_50':     cross,
            'drawdown':        float(dd),
            'is_active':       is_active,
            'buy_price':       buy_price if is_active else None,
            'curr_price':      cur_nav,
            'trail_alert':     trail_alert,
            'hwm':             hwm_data.get(isin, {}).get('hwm') if is_active else None,
            'hwm_date':        hwm_data.get(isin, {}).get('hwm_date') if is_active else None,
            'return_1m':       item.get('return_1m'),
            'return_1y':       item.get('return_1y'),
            'return_ytd':      item.get('return_ytd'),
        }
        rows.append(row)

        # Spejder-logik er flyttet til etf_spejder.py

    # Gem opdaterede HWM
    save_hwm(hwm_data)

    # Aggregerede data
    avg_portfolio_return = (
        sum(active_week_returns) / len(active_week_returns)
        if active_week_returns else 0.0
    )

    # Top/bund 5 på ugeafkast
    top_up   = sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5]
    top_down = sorted(rows, key=lambda x: x['week_change_pct'])[:5]

    # Chart data — top 10 momentum
    chart_data = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]

    # Portfolio alerts (kraftige fald på ugen)
    portfolio_alerts = [
        {'msg': '⚠️ Kraftigt fald', 'name': r['name'], 'change': r['week_change_pct']}
        for r in rows
        if r['is_active'] and r['week_change_pct'] < -3.0
    ]

    # Render template
    template_text  = TEMPLATE_FILE.read_text(encoding="utf-8")
    jinja_template = Template(template_text)

    # --- SEKTOR HEATMAP ---
    active_fund_data = [r for r in rows if r['is_active']]
    heatmap_data     = build_heatmap(portfolio, active_fund_data, watchlist=watchlist)
    heatmap_warning  = get_concentration_warning(heatmap_data)

    html = jinja_template.render(
        week_number          = datetime.now().isocalendar()[1],
        report_date          = datetime.now().strftime("%d. %B %Y"),
        avg_portfolio_return = round(avg_portfolio_return, 2),
        portfolio_alerts     = portfolio_alerts,
        trail_stop_alerts    = trail_stop_alerts,
        trail_stop_pct       = TRAIL_STOP_PCT,
        spejder_hits         = spejder_hits_all,
        spejder_hurtige      = spejder_hurtige,
        spejder_stabile      = spejder_stabile,
        spejder_meta         = spejder_meta,
        top_up               = top_up,
        top_down             = top_down,
        rows                 = sorted(rows, key=lambda x: (not x['is_active'], -x['momentum'])),
        chart_labels         = [r['name'][:20] for r in chart_data],
        chart_values         = [r['momentum'] for r in chart_data],
        heatmap_data         = heatmap_data,
        heatmap_warning      = heatmap_warning,
    )

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(html, encoding="utf-8")

    print(f"✅ ETF Ugerapport genereret: {REPORT_FILE}")
    print(f"   {len(rows)} ETF'er analyseret")
    print(f"   {len(spejder_hurtige)} hurtige + {len(spejder_stabile)} stabile Spejder-kandidater")
    if trail_stop_alerts:
        print(f"   ⚠️  {len(trail_stop_alerts)} trail stop-advarsel(er)")


if __name__ == "__main__":
    build_weekly()
