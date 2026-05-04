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
    check_trail_stop, is_trading_day,
)

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE   = ROOT / "data/history.json"
LATEST_FILE    = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE  = ROOT / "templates/weekly.html.j2"
REPORT_FILE    = ROOT / "build/weekly.html"
HWM_FILE       = ROOT / "data/high_water_marks.json"

TRAIL_STOP_PCT = 3.0


# ==========================================
# HWM — fil-håndtering (ikke i utils.py)
# ==========================================

def load_high_water_marks():
    if HWM_FILE.exists():
        try:
            with open(HWM_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_high_water_marks(hwm_data):
    HWM_FILE.parent.mkdir(exist_ok=True)
    with open(HWM_FILE, "w", encoding="utf-8") as f:
        json.dump(hwm_data, f, indent=2)


# ==========================================
# HOVEDFUNKTION
# ==========================================

def build_weekly():
    print("🔄 Starter generering af ugerapport...")

    for f in [HISTORY_FILE, LATEST_FILE, PORTFOLIO_FILE, TEMPLATE_FILE]:
        if not f.exists():
            print(f"❌ FEJL: Mangler fil: {f}")
            return

    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        history = json.load(f)
    with open(LATEST_FILE, 'r', encoding='utf-8') as f:
        latest = json.load(f)
    with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        portfolio = json.load(f)

    portfolio_isins = {
        isin for isin, info in portfolio.items()
        if info.get("active", False)
    }
    print(f"📋 Aktive positioner: {len(portfolio_isins)} fonde")

    hwm_data          = load_high_water_marks()
    today_str         = datetime.now().strftime('%Y-%m-%d')
    trail_stop_alerts = []

    rows = []
    active_week_returns = []

    for item in latest:
        isin    = item['isin']
        p_dict  = history.get(isin, {})

        # Kun handelsdage — samme filtrering som daily
        sorted_dates = [d for d in sorted(p_dict.keys()) if is_trading_day(d)]
        p_list       = [p_dict[d] for d in sorted_dates]

        if not p_list:
            continue

        cur_nav   = item.get('nav') or 0.0
        is_active = isin in portfolio_isins

        # Sikr dagens NAV er med
        if not p_list or p_list[-1] != cur_nav:
            p_list.append(cur_nav)

        # --- MOMENTUM (Afstand til bedste tilgængelige MA) ---
        ma_val, ma_label = get_best_ma(p_list)

        if ma_val and cur_nav:
            momentum = round(((cur_nav / ma_val) - 1) * 100, 2)
        else:
            momentum = round(item.get('return_1m') or 0.0, 2)
            ma_label = "1M proxy"

        trend_state = "BULL" if momentum > 0 else "BEAR"

        ytd = calculate_ytd(p_dict)
        dd  = calculate_drawdown(p_list)
        rsi = get_rsi(p_list, 14)

        # Total afkast fra køb (hvis aktiv) eller fra tidligste historik
        if is_active and isin in portfolio:
            buy_price = portfolio[isin].get('buy_price', 0)
            total_ret = round(((cur_nav / buy_price) - 1) * 100, 2) if buy_price else 0.0
        else:
            buy_price = 0
            total_ret = round(((cur_nav / p_list[0]) - 1) * 100, 2) if p_list else 0.0

        week_change = float(item.get('return_1w') or 0.0)

        if is_active:
            active_week_returns.append(week_change)

        # --- TRAILING STOP CHECK (kun aktive fonde) ---
        trail_alert = None
        if is_active and buy_price and cur_nav:
            hwm_entry, trail_alert = check_trail_stop(
                isin, cur_nav, buy_price, hwm_data, today_str, TRAIL_STOP_PCT
            )
            hwm_data[isin] = hwm_entry
            if trail_alert:
                trail_alert["name"] = portfolio[isin].get("name", isin)
                trail_stop_alerts.append(trail_alert)
                print(
                    f"🔔 TRAIL STOP: {trail_alert['name']} faldet {trail_alert['fall_pct']}% "
                    f"fra top {trail_alert['hwm']} ({trail_alert['hwm_date']}) → nu {trail_alert['curr']}"
                )

        rows.append({
            'isin':            isin,
            'name':            item.get('name', isin),
            'week_change_pct': week_change,
            'total_return':    float(total_ret),
            'trend_state':     trend_state,
            'ma_label':        ma_label,
            'momentum':        momentum,
            'ytd_return':      float(ytd),
            'drawdown':        float(dd),
            'is_active':       is_active,
            'rsi':             rsi,
            'buy_price':       buy_price if is_active else None,
            'curr_price':      cur_nav,
            'trail_alert':     trail_alert,
            'hwm':             hwm_data.get(isin, {}).get('hwm') if is_active else None,
            'hwm_date':        hwm_data.get(isin, {}).get('hwm_date') if is_active else None,
        })

    # Gem opdaterede HWM (deles med daily og monthly)
    save_high_water_marks(hwm_data)

    # --- AGGREGEREDE DATA ---
    avg_portfolio_return = (
        sum(active_week_returns) / len(active_week_returns)
        if active_week_returns else 0.0
    )

    chart_data = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]

    portfolio_alerts = [
        {'msg': '⚠️ Kraftigt fald', 'name': r['name'], 'change': r['week_change_pct']}
        for r in rows
        if r['is_active'] and r['week_change_pct'] < -3.0
    ]

    market_opportunities = [
        r for r in rows
        if not r['is_active'] and r['momentum'] > 2.0 and r['trend_state'] == "BULL"
    ][:8]

    # --- TEMPLATE RENDERING ---
    template_text  = TEMPLATE_FILE.read_text(encoding="utf-8")
    jinja_template = Template(template_text)

    færdig_html = jinja_template.render(
        week_number          = datetime.now().isocalendar()[1],
        report_date          = datetime.now().strftime("%d. %B %Y"),
        avg_portfolio_return = round(avg_portfolio_return, 2),
        portfolio_alerts     = portfolio_alerts,
        trail_stop_alerts    = trail_stop_alerts,
        trail_stop_pct       = TRAIL_STOP_PCT,
        market_opportunities = market_opportunities,
        top_up               = sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down             = sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        rows                 = sorted(rows, key=lambda x: (not x['is_active'], -x['momentum'])),
        chart_labels         = [r['name'][:20] for r in chart_data],
        chart_values         = [r['momentum'] for r in chart_data],
    )

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(færdig_html, encoding="utf-8")

    print(f"✅ Succes! Ugerapport genereret: {REPORT_FILE}")
    print(f"   Aktive fonde: {len(active_week_returns)}, Snit ugeafkast: {avg_portfolio_return:.2f}%")
    if trail_stop_alerts:
        print(f"   ⚠️  {len(trail_stop_alerts)} trail stop-advarsel(er) i rapporten.")


if __name__ == "__main__":
    build_weekly()
