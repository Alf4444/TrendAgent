import json
import sys
import time
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# Tilføj reporting/ til Python-stien så utils.py kan importeres
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    get_ma, get_best_ma, get_rsi, get_volatility,
    calculate_drawdown, get_cross_signal, get_trend_state,
    check_trail_stop, days_since_hwm, is_trading_day,
)

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT           = Path(__file__).resolve().parents[1]
DATA_FILE      = ROOT / "data/pfa_latest.json"
HISTORY_FILE   = ROOT / "data/pfa_history.json"
PORTFOLIO_FILE = ROOT / "config/pfa_portfolio.json"
HWM_FILE       = ROOT / "data/pfa_hwm.json"
TEMPLATE_FILE  = ROOT / "templates/pfa_daily.html.j2"
REPORT_FILE    = ROOT / "build/pfa_daily.html"
README_FILE    = ROOT / "README.md"

# Stop-loss grænser
DRAWDOWN_ALERT_PCT     = -10.0   # Fald fra ATH
TOTAL_RETURN_ALERT_PCT = -8.0    # Tab fra købspris
TRAIL_STOP_PCT         = 3.0     # HWM Trail Stop (deles med weekly/monthly)


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


def build_report():

    # 1. RETRY-LOGIK — vent på friske data (maks 3 forsøg x 5 min)
    max_retries = 3
    retry_delay = 300
    latest_data = []

    for attempt in range(max_retries):
        if not DATA_FILE.exists():
            print(f"FEJL: {DATA_FILE} mangler.")
            return

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            latest_data = json.load(f)

        file_mod_time = datetime.fromtimestamp(DATA_FILE.stat().st_mtime).date()
        if file_mod_time == datetime.now().date():
            print(f"Data er frisk (fra i dag {file_mod_time}). Starter build...")
            break
        else:
            if attempt < max_retries - 1:
                print(f"Forsøg {attempt+1}: Data er fra i går. Venter {retry_delay//60} min...")
                time.sleep(retry_delay)
            else:
                print("Advarsel: Kører på gårsdagens data — PFA har ikke opdateret endnu.")

    # 2. INDLÆS FILER
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning: {e}")
        return

    hwm_data  = load_high_water_marks()
    today_str = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')

    processed_list = []
    daily_alerts   = []   # Samler alle signaler til mail-beslutning

    # 3. BEHANDL HVER FOND
    for item in latest_data:
        isin = item.get('isin')
        nav  = item.get('nav')
        if nav is None or isin is None:
            continue

        # Historik — kun handelsdage
        price_dict   = history.get(isin, {})
        sorted_dates = [d for d in sorted(price_dict.keys()) if is_trading_day(d)]
        prices       = [price_dict[d] for d in sorted_dates]

        # Sikr dagens NAV er med
        if not prices or prices[-1] != nav:
            prices.append(nav)

        # --- TEKNISKE BEREGNINGER via utils.py ---
        ma20       = get_ma(prices, 20)
        ma50       = get_ma(prices, 50)
        ma200      = get_ma(prices, 200)
        ma_val, ma_label = get_best_ma(prices)
        rsi        = get_rsi(prices, 14)
        volatility = get_volatility(prices, 20)
        drawdown   = calculate_drawdown(prices)
        cross      = get_cross_signal(prices)
        t_state    = get_trend_state(prices)

        # Afstand til bedste tilgængelige MA (MA200 > MA50 > MA20)
        dist_ma200 = round(((nav - ma_val) / ma_val * 100), 2) if ma_val else 0.0

        # Daglig ændring
        prev_nav = prices[-2] if len(prices) > 1 else nav
        day_chg  = round(((nav - prev_nav) / prev_nav * 100), 2) if prev_nav else 0.0

        # KØB/SALG signal — kun ved MA200-kryds (kræver nok historik)
        signal     = "–"
        has_signal = 0
        if ma200:
            if nav > ma200 and prev_nav <= ma200:
                signal, has_signal = "🚀 KØB", 1
            elif nav < ma200 and prev_nav >= ma200:
                signal, has_signal = "⚠️ SALG", 1

        # Portefølje-data
        p_info       = portfolio.get(isin, {})
        is_active    = p_info.get('active', False)
        buy_p        = p_info.get('buy_price')
        total_return = round(((nav - buy_p) / buy_p * 100), 2) if is_active and buy_p else None

        # Stop-loss flag (drawdown eller tab fra køb)
        stop_alert = (
            drawdown <= DRAWDOWN_ALERT_PCT or
            (is_active and total_return is not None and total_return <= TOTAL_RETURN_ALERT_PCT)
        )

        # Trail Stop (kun aktive fonde — deler HWM med weekly/monthly)
        trail_alert = None
        if is_active and buy_p and nav:
            hwm_entry, trail_alert = check_trail_stop(
                isin, nav, buy_p, hwm_data, today_str, TRAIL_STOP_PCT
            )
            hwm_data[isin] = hwm_entry
            if trail_alert:
                trail_alert["name"] = p_info.get("name", isin)

        # RSI-extremer
        rsi_alert = None
        if rsi is not None:
            if rsi >= 70:
                rsi_alert = "overkøbt"
            elif rsi <= 30:
                rsi_alert = "oversolgt"

        # Saml signaler der skal med i mail-beslutningen
        has_any_alert = (
            has_signal or
            stop_alert or
            trail_alert is not None or
            cross != "–" or
            rsi_alert is not None
        )
        if has_any_alert:
            daily_alerts.append({
                "name":        item.get('name', isin),
                "isin":        isin,
                "signal":      signal,
                "cross":       cross,
                "stop_alert":  stop_alert,
                "trail_alert": trail_alert,
                "rsi_alert":   rsi_alert,
                "day_chg":     day_chg,
                "t_state":     t_state,
                "is_active":   is_active,
            })

        processed_list.append({
            'isin':         isin,
            'name':         item.get('name'),
            'day_chg':      day_chg,
            'dist_ma200':   dist_ma200,
            'ma_label':     ma_label,
            'rsi':          rsi,
            'rsi_alert':    rsi_alert,
            'volatility':   volatility,
            'signal':       signal,
            'has_signal':   has_signal,
            'is_active':    is_active,
            'drawdown':     drawdown,
            'cross_20_50':  cross,
            'total_return': total_return,
            'stop_alert':   stop_alert,
            'trail_alert':  trail_alert,
            't_state':      t_state,
            'buy_price':    buy_p if is_active else None,
            'hwm':          hwm_data.get(isin, {}).get('hwm') if is_active else None,
        })

    # Gem opdateret HWM
    save_high_water_marks(hwm_data)

    # 4. SORTERING — aktive øverst, derefter signaler, derefter alfabetisk
    processed_list.sort(key=lambda x: (
        not x['is_active'],
        x['signal'] == "–",
        x['name'] or ""
    ))

    outliers = sorted(processed_list, key=lambda x: x['day_chg'] or 0, reverse=True)
    top_3    = outliers[:3]
    bottom_3 = outliers[-3:][::-1]

    # 5. OPDATER README.MD
    readme_lines = [
        f"# 📈 TrendAgent Fokus",
        f"**Opdateret:** {timestamp}\n",
        "| | Fond | Signal | RSI | Afkast % | Trend | MA % | Cross |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for d in processed_list:
        if d['is_active'] or d['has_signal']:
            ret     = f"{d['total_return']:+.1f}%" if d['total_return'] is not None else "–"
            rsi_val = f"{d['rsi']:.0f}" if d['rsi'] is not None else "–"
            prefix  = "⚠️ " if d.get('stop_alert') else ""
            readme_lines.append(
                f"| {'⭐' if d['is_active'] else '🔍'} | "
                f"{prefix}{(d['name'] or '')[:25]} | "
                f"{d['signal']} | {rsi_val} | {ret} | {d['t_state']} | "
                f"{d['dist_ma200']:+.1f}% | {d['cross_20_50']} |"
            )

    try:
        README_FILE.write_text("\n".join(readme_lines), encoding="utf-8")
    except Exception as e:
        print(f"Kunne ikke skrive README: {e}")

    # 6. RENDER HTML
    if not TEMPLATE_FILE.exists():
        print(f"❌ Template mangler: {TEMPLATE_FILE}")
        return

    template   = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(
        timestamp     = timestamp,
        funds         = processed_list,
        top_3         = top_3,
        bottom_3      = bottom_3,
        daily_alerts  = daily_alerts,
        trail_stop_pct = TRAIL_STOP_PCT,
    )
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")

    active_alerts = len(daily_alerts)
    print(f"✅ Daily rapport færdig: {len(processed_list)} fonde analyseret.")
    if active_alerts:
        print(f"   🔔 {active_alerts} aktive signaler — mail sendes af workflow.")
    else:
        print(f"   ✅ Ingen aktive signaler i dag.")


if __name__ == "__main__":
    build_report()
