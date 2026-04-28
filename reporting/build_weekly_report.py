import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

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

# Trailing Stop tærskel i % — samme værdi som i monthly for konsistens.
# Ændres ét sted her, og begge rapporter er synkroniserede.
TRAIL_STOP_PCT = 3.0


# ==========================================
# TEKNISKE HJÆLPEFUNKTIONER
# ==========================================

def get_ma(prices, window):
    """
    Beregner Simple Moving Average (SMA) for de seneste 'window' datapunkter.
    Returnerer None hvis der ikke er nok data.
    """
    if not isinstance(prices, list) or len(prices) < window:
        return None
    relevant = [p for p in prices[-window:] if p is not None]
    if len(relevant) < window:
        return None
    return sum(relevant) / window


def get_best_ma(prices):
    """
    Returnerer det bedste tilgængelige glidende gennemsnit og label.
    Prioritering: MA200 > MA50 > MA20 > None.

    Baggrund: Vi opbygger historik gradvist. MA200 kræver 200 datapunkter
    (ca. 9 måneder med daglige opdateringer). Indtil da bruger vi MA50 eller MA20
    som proxy, så Trend-kolonnen ikke viser BEAR for alle fonde permanent.
    """
    for window, label in [(200, "MA200"), (50, "MA50"), (20, "MA20")]:
        ma = get_ma(prices, window)
        if ma is not None:
            return ma, label
    return None, None


def get_rsi(prices, window=14):
    """
    Beregner Relative Strength Index (RSI).
    Returnerer None hvis der ikke er nok data.
    """
    if not isinstance(prices, list) or len(prices) <= window:
        return None

    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    recent_deltas = deltas[-window:]

    gains  = [d if d > 0 else 0 for d in recent_deltas]
    losses = [abs(d) if d < 0 else 0 for d in recent_deltas]

    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calculate_ytd(prices_dict):
    """
    Beregner afkast siden årets start (Year-To-Date) fra historikken.
    Finder seneste kurs fra forrige år som startpunkt.
    """
    if not prices_dict:
        return 0.0

    dates = sorted(prices_dict.keys())
    cur_year = datetime.now().year
    start_price = None

    for d in reversed(dates):
        if d < f"{cur_year}-01-01":
            start_price = prices_dict[d]
            break

    if start_price is None:
        for d in dates:
            if d.startswith(str(cur_year)):
                start_price = prices_dict[d]
                break

    if not start_price or start_price == 0:
        return 0.0

    current_price = prices_dict[dates[-1]]
    return round(((current_price / start_price) - 1) * 100, 2)


def calculate_drawdown(prices_list):
    """
    Beregner aktuelt fald fra All-Time High (ATH) i den tilgængelige historik.
    Returneres som negativ procent (fx -12.5 = 12.5% under ATH).
    """
    if not prices_list:
        return 0.0

    ath = max(prices_list)
    if ath == 0:
        return 0.0

    current = prices_list[-1]
    return round(((current / ath) - 1) * 100, 2)


# ==========================================
# TRAILING STOP — HIGH WATER MARK
# ==========================================

def load_high_water_marks():
    """
    Indlæser High Water Marks fra fælles fil (deles med monthly).
    Struktur: { "PFA000002703": { "hwm": 430.5, "hwm_date": "2026-04-10" }, ... }
    """
    if HWM_FILE.exists():
        try:
            with open(HWM_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_high_water_marks(hwm_data):
    """Gemmer opdaterede High Water Marks til fælles fil."""
    HWM_FILE.parent.mkdir(exist_ok=True)
    with open(HWM_FILE, "w", encoding="utf-8") as f:
        json.dump(hwm_data, f, indent=2)


def check_trail_stop(isin, curr_price, buy_price, hwm_data, today_str):
    """
    Opdaterer High Water Mark og returnerer en trail stop-advarsel hvis
    fonden er faldet mere end TRAIL_STOP_PCT % fra sit hidtidige toppunkt.

    Logik:
    1. Hvis curr_price > hidtidig HWM → opdater HWM (ny top sat).
    2. Beregn fald fra HWM: (curr / hwm - 1) * 100
    3. Hvis fald > TRAIL_STOP_PCT → returner advarsel-dict.

    HWM initialiseres til buy_price hvis ingen historik findes endnu.

    Returnerer (opdateret hwm_entry, advarsel_dict_eller_None).
    """
    entry = hwm_data.get(isin, {})
    hwm   = entry.get("hwm", buy_price)

    # Ny top?
    if curr_price > hwm:
        hwm = curr_price
        entry = {"hwm": round(hwm, 2), "hwm_date": today_str}
        print(f"[HWM] {isin}: Ny top sat til {hwm} ({today_str})")

    fall_pct = ((curr_price / hwm) - 1) * 100 if hwm > 0 else 0.0

    alert = None
    if fall_pct <= -TRAIL_STOP_PCT:
        alert = {
            "isin":      isin,
            "hwm":       round(hwm, 2),
            "hwm_date":  entry.get("hwm_date", "?"),
            "curr":      round(curr_price, 2),
            "fall_pct":  round(fall_pct, 2),
            "buy_price": round(buy_price, 2),
            "total_ret": round(((curr_price / buy_price) - 1) * 100, 2) if buy_price else 0,
        }

    return entry, alert


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

    # Indlæs HWM — opdateres løbende nedenfor
    hwm_data          = load_high_water_marks()
    today_str         = datetime.now().strftime('%Y-%m-%d')
    trail_stop_alerts = []

    rows = []
    active_week_returns = []

    for item in latest:
        isin    = item['isin']
        p_dict  = history.get(isin, {})
        s_dates = sorted(p_dict.keys())
        p_list  = [p_dict[d] for d in s_dates]

        if not p_list:
            continue

        cur_nav   = item.get('nav') or 0.0
        is_active = isin in portfolio_isins

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
                isin, cur_nav, buy_price, hwm_data, today_str
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
            # Trail stop info til tabellen (None hvis ingen advarsel)
            'trail_alert':     trail_alert,
            'hwm':             hwm_data.get(isin, {}).get('hwm') if is_active else None,
            'hwm_date':        hwm_data.get(isin, {}).get('hwm_date') if is_active else None,
        })

    # Gem opdaterede HWM (deles med monthly)
    save_high_water_marks(hwm_data)

    # --- AGGREGEREDE DATA ---
    avg_portfolio_return = (
        sum(active_week_returns) / len(active_week_returns)
        if active_week_returns else 0.0
    )

    chart_data = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]

    # Ugentlige kursfald-alarmer (> 3% ned på ugen)
    portfolio_alerts = [
        {'msg': '⚠️ Kraftigt fald', 'name': r['name'], 'change': r['week_change_pct']}
        for r in rows
        if r['is_active'] and r['week_change_pct'] < -3.0
    ]

    # Markedsmuligheder: ikke ejet, positivt momentum, BULL trend
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
