import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE  = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE  = ROOT / "templates/weekly.html.j2"
REPORT_FILE    = ROOT / "build/weekly.html"

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
    Returnerer det bedste tilgængelige glidende gennemsnit og hvilket niveau det er.
    Prioritering: MA200 > MA50 > MA20 > None.

    Baggrund: Vi opbygger historik gradvist. MA200 kræver 200 datapunkter
    (ca. 9 måneder med daglige opdateringer). Indtil da bruger vi MA50 eller MA20
    som proxy, så Trend-kolonnen ikke viser BEAR for alle fonde permanent.

    Returnerer (ma_værdi, label) fx (412.5, "MA50") eller (None, None).
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

    # Find seneste kurs fra forrige år
    for d in reversed(dates):
        if d < f"{cur_year}-01-01":
            start_price = prices_dict[d]
            break

    # Backup: første kurs i år, hvis ingen data fra forrige år
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
# HOVEDFUNKTION
# ==========================================

def build_weekly():
    print("🔄 Starter generering af ugerapport...")

    # Validering af filer
    for f in [HISTORY_FILE, LATEST_FILE, PORTFOLIO_FILE, TEMPLATE_FILE]:
        if not f.exists():
            print(f"❌ FEJL: Mangler fil: {f}")
            return

    # Indlæs data
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        history = json.load(f)
    with open(LATEST_FILE, 'r', encoding='utf-8') as f:
        latest = json.load(f)
    with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        portfolio = json.load(f)

    # -------------------------------------------------------
    # RETTELSE: portfolio.json har formatet:
    #   { "PFA000002703": { "active": true, "buy_price": 415.21, ... }, ... }
    #
    # Den gamle kode forsøgte p_data.get("active_holdings", []) som altid
    # returnerede [] — alle fonde blev markeret som ikke-aktive, og
    # "Ugens Afkast" blev derfor altid 0.00%.
    # -------------------------------------------------------
    portfolio_isins = {
        isin for isin, info in portfolio.items()
        if info.get("active", False)
    }
    print(f"📋 Aktive positioner: {len(portfolio_isins)} fonde")

    rows = []
    active_week_returns = []

    for item in latest:
        isin    = item['isin']
        p_dict  = history.get(isin, {})
        s_dates = sorted(p_dict.keys())
        p_list  = [p_dict[d] for d in s_dates]

        if not p_list:
            continue

        cur_nav = item.get('nav') or 0.0

        # --- MOMENTUM (Afstand til bedste tilgængelige MA) ---
        # RETTELSE: Bruger nu MA200/MA50/MA20 som fallback i stedet for 0.0.
        # Momentum 0.0 for alle fonde gjorde grafen tom og alle trends til BEAR.
        ma_val, ma_label = get_best_ma(p_list)

        if ma_val and cur_nav:
            momentum = round(((cur_nav / ma_val) - 1) * 100, 2)
        else:
            # Ikke nok historik til noget MA — brug return_1m som proxy
            momentum = round(item.get('return_1m') or 0.0, 2)
            ma_label = "1M proxy"

        # Trend: BULL hvis kurs over MA, BEAR hvis under
        trend_state = "BULL" if momentum > 0 else "BEAR"

        # Øvrige nøgletal
        ytd = calculate_ytd(p_dict)
        dd  = calculate_drawdown(p_list)
        rsi = get_rsi(p_list, 14)

        # Total afkast fra køb (hvis i portefølje) eller fra tidligste historik
        is_active = isin in portfolio_isins
        if is_active and isin in portfolio:
            buy_price = portfolio[isin].get('buy_price', 0)
            total_ret = round(((cur_nav / buy_price) - 1) * 100, 2) if buy_price else 0.0
        else:
            total_ret = round(((cur_nav / p_list[0]) - 1) * 100, 2) if p_list else 0.0

        week_change = float(item.get('return_1w') or 0.0)

        if is_active:
            active_week_returns.append(week_change)

        rows.append({
            'isin':           isin,
            'name':           item.get('name', isin),
            'week_change_pct': week_change,
            'total_return':   float(total_ret),
            'trend_state':    trend_state,
            'ma_label':       ma_label,          # Fortæller templaten hvilket MA der bruges
            'momentum':       momentum,
            'ytd_return':     float(ytd),
            'drawdown':       float(dd),
            'is_active':      is_active,
            'rsi':            rsi,
            'buy_price':      portfolio.get(isin, {}).get('buy_price') if is_active else None,
            'curr_price':     cur_nav,
        })

    # --- AGGREGEREDE DATA ---
    avg_portfolio_return = (
        sum(active_week_returns) / len(active_week_returns)
        if active_week_returns else 0.0
    )

    # Top 10 til momentum-grafen — sorteres på momentum-værdi
    chart_data = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]

    # Alarmer: aktive fonde der er faldet mere end 3% på ugen
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
    template_text   = TEMPLATE_FILE.read_text(encoding="utf-8")
    jinja_template  = Template(template_text)

    færdig_html = jinja_template.render(
        week_number          = datetime.now().isocalendar()[1],
        report_date          = datetime.now().strftime("%d. %B %Y"),
        avg_portfolio_return = round(avg_portfolio_return, 2),
        portfolio_alerts     = portfolio_alerts,
        market_opportunities = market_opportunities,
        top_up               = sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down             = sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        # Aktive fonde øverst, derefter sorteret på momentum
        rows                 = sorted(rows, key=lambda x: (not x['is_active'], -x['momentum'])),
        chart_labels         = [r['name'][:20] for r in chart_data],
        chart_values         = [r['momentum'] for r in chart_data],
    )

    # --- GEM RAPPORT ---
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(færdig_html, encoding="utf-8")

    print(f"✅ Succes! Ugerapport genereret: {REPORT_FILE}")
    print(f"   Aktive fonde: {len(active_week_returns)}, Snit ugeafkast: {avg_portfolio_return:.2f}%")


if __name__ == "__main__":
    build_weekly()
