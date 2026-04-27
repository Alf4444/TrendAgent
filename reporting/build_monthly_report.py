import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION & ROBUSTE STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
DATA_FILE      = ROOT / "data/latest.json"
HISTORY_FILE   = ROOT / "data/history.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE  = ROOT / "templates/monthly.html.j2"
REPORT_FILE    = ROOT / "build/monthly.html"
HWM_FILE       = ROOT / "data/high_water_marks.json"   # Trail Stop historik

# RETTELSE: PFA000002735 er Magna Eastern European (solgt fond) — ikke et benchmark.
# PFA000002233 = PFA Indeks Globale Aktier er den korrekte brede benchmark-proxy.
BENCHMARK_ISIN = "PFA000002233"

# Hvor mange procent fonden må falde fra sit High Water Mark
# før der genereres en trail stop-advarsel i rapporten.
TRAIL_STOP_PCT = 3.0


# ==========================================
# TEKNISKE HJÆLPEFUNKTIONER
# ==========================================

def get_ma(prices, window):
    """SMA for de seneste 'window' datapunkter. None hvis ikke nok data."""
    if not prices or len(prices) < window:
        return None
    relevant = [p for p in prices[-window:] if p is not None]
    if len(relevant) < window:
        return None
    return round(sum(relevant) / window, 2)


def get_best_ma(prices):
    """
    Returnerer bedste tilgængelige MA og label.
    Prioritering: MA200 > MA50 > MA20.
    Bruges så vi ikke viser N/A for alle fonde mens historikken opbygges.
    """
    for window, label in [(200, "MA200"), (50, "MA50"), (20, "MA20")]:
        ma = get_ma(prices, window)
        if ma is not None:
            return ma, label
    return None, None


def get_rsi(prices, window=14):
    """RSI. None hvis ikke nok data."""
    if not prices or len(prices) <= window:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [d if d > 0 else 0 for d in deltas[-window:]]
    losses = [abs(d) if d < 0 else 0 for d in deltas[-window:]]
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def get_ranking_data(latest_list):
    """Rangerer alle fonde efter 1M afkast. Returnerer rank_map og total antal."""
    sorted_list = sorted(latest_list, key=lambda x: x.get('return_1m') or -999, reverse=True)
    rank_map = {item['isin']: index + 1 for index, item in enumerate(sorted_list)}
    return rank_map, len(sorted_list)


def get_trend_velocity(f):
    """
    Sammenligner ugens afkast mod månedens gennemsnit.
    Accelererer = fonden er hurtigere nu end gennemsnittet for måneden.
    Bremser     = fonden er langsommere/svagere end månedssnittet.
    """
    r1w = f.get('return_1w') or 0
    r1m = f.get('return_1m') or 0
    avg_weekly_in_month = r1m / 4
    if r1w > avg_weekly_in_month and r1w > 0:
        return "🚀 Accelererer", "trend-up"
    elif r1w < avg_weekly_in_month:
        return "📉 Bremser", "trend-down"
    return "➡️ Stabil", "trend-side"


def get_momentum_status(f, rank):
    """
    Klassificerer en fonds momentum baseret på markedsrang og 1M afkast.
    Top Performer = Top 5 med positivt afkast.
    Stabil        = Top 7.
    Slower        = Udenfor top 7 eller negativt afkast.
    Outperformed  = Udenfor top 10 — andre løber markant hurtigere.
    """
    r1m = f.get('return_1m') or 0
    if rank > 10:
        return "🛑 Outperformed", "momentum-flat"
    if r1m < 0 or rank > 7:
        return "⚠️ Slower", "momentum-slow"
    if rank <= 5 and r1m > 0:
        return "🚀 Top Performer", "momentum-fast"
    return "✅ Stabil", "momentum-stable"


def validate_data(latest_map, portfolio):
    """Validerer at benchmark og aktive fonde findes i datasættet."""
    warnings = []
    if BENCHMARK_ISIN not in latest_map:
        warnings.append(f"ADVARSEL: Benchmark ISIN {BENCHMARK_ISIN} mangler i data.")
    for isin, p_info in portfolio.items():
        if p_info.get('active', False):
            if isin not in latest_map:
                warnings.append(f"ADVARSEL: Aktiv fond {p_info.get('name', isin)} ({isin}) mangler i PFA-data.")
            if not p_info.get('buy_price') or p_info['buy_price'] <= 0:
                warnings.append(f"ADVARSEL: Købspris mangler for {p_info.get('name', isin)}.")
    return warnings


# ==========================================
# TRAIL STOP — HIGH WATER MARK
# ==========================================

def load_high_water_marks():
    """
    Indlæser High Water Marks fra fil.
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
    """Gemmer opdaterede High Water Marks til fil."""
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
    hwm   = entry.get("hwm", buy_price)   # Start fra købspris hvis ingen HWM endnu

    # Ny top?
    if curr_price > hwm:
        hwm = curr_price
        entry = {"hwm": round(hwm, 2), "hwm_date": today_str}
        print(f"[HWM] {isin}: Ny top sat til {hwm} ({today_str})")

    # Fald fra top
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

def build_monthly():
    if not DATA_FILE.exists() or not PORTFOLIO_FILE.exists() or not HISTORY_FILE.exists():
        print("KRITISK FEJL: Data- eller historikfil mangler.")
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            latest_list = json.load(f)
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning: {e}")
        return

    rank_map, total_market_count = get_ranking_data(latest_list)
    latest_map = {item['isin']: item for item in latest_list}
    validation_warnings = validate_data(latest_map, portfolio)

    now        = datetime.now()
    today_str  = now.strftime('%Y-%m-%d')
    timestamp  = now.strftime('%d-%m-%Y %H:%M')
    week_number = now.strftime('%V')

    # Indlæs High Water Marks
    hwm_data = load_high_water_marks()

    active_rows          = []
    sold_rows            = []
    active_returns_total = []
    trail_stop_alerts    = []   # Samler alle trail stop-advarsler til rapporten

    for isin, p_info in portfolio.items():
        if isin not in latest_map:
            continue

        official  = latest_map[isin]
        rank      = rank_map.get(isin, 99)
        curr_p    = official.get('nav') or 0
        buy_p     = p_info.get('buy_price', 0)
        is_active = p_info.get('active', False)

        total_return = round(((curr_p - buy_p) / buy_p * 100), 2) if buy_p > 0 else 0

        # MA & RSI fra historik
        prices = []
        if isin in history:
            sorted_dates = sorted(history[isin].keys())
            prices = [history[isin][d] for d in sorted_dates]

        rsi_val        = get_rsi(prices, 14)
        ma_val, ma_label = get_best_ma(prices)

        m_label, m_class = get_momentum_status(official, rank)
        t_label, t_class = get_trend_velocity(official)

        # T-state baseret på bedste tilgængelige MA
        if ma_val and curr_p:
            t_state = "BULL" if curr_p > ma_val else "BEAR"
        else:
            t_state = "N/A"

        fund_data = {
            "isin":           isin,
            "name":           p_info.get('name', isin),
            "rank":           rank,
            "buy_date":       p_info.get('buy_date', 'N/A'),
            "buy_price":      buy_p,
            "curr_price":     curr_p,
            "return_1w":      official.get('return_1w') or 0,
            "return_1m":      official.get('return_1m') or 0,
            "trend_label":    t_label,
            "trend_class":    t_class,
            "momentum_label": m_label,
            "momentum_class": m_class,
            "total_return":   total_return,
            "rsi":            rsi_val,
            "ma":             ma_val,
            "ma_label":       ma_label,
            "t_state":        t_state,
            "is_active":      is_active,
        }

        if is_active:
            active_rows.append(fund_data)
            active_returns_total.append(total_return)

            # --- TRAIL STOP CHECK ---
            hwm_entry, alert = check_trail_stop(isin, curr_p, buy_p, hwm_data, today_str)
            hwm_data[isin] = hwm_entry
            if alert:
                alert["name"] = p_info.get('name', isin)
                trail_stop_alerts.append(alert)
                print(
                    f"🔔 TRAIL STOP: {alert['name']} faldet {alert['fall_pct']}% "
                    f"fra top {alert['hwm']} ({alert['hwm_date']}) → nu {alert['curr']}"
                )
        else:
            fund_data["sell_date"]  = p_info.get('sell_date', 'N/A')
            fund_data["sell_price"] = p_info.get('sell_price', 'N/A')
            sold_rows.append(fund_data)

    # Gem opdaterede High Water Marks
    save_high_water_marks(hwm_data)

    # --- TOP 5 MARKEDSMULIGHEDER ---
    unsorted_opps = [
        i for i in latest_list
        if i['isin'] not in portfolio or not portfolio[i['isin']].get('active', False)
    ]
    sorted_opps = sorted(unsorted_opps, key=lambda x: x.get('return_1m') or 0, reverse=True)[:5]
    market_opps = []
    for o in sorted_opps:
        t_label_o, _ = get_trend_velocity(o)
        market_opps.append({
            "name":       o.get('name', o['isin']),
            "return_1m":  o.get('return_1m') or 0,
            "return_ytd": o.get('return_ytd') or 0,
            "rank":       rank_map.get(o['isin']),
            "trend_label": t_label_o,
        })

    sell_signals = [f for f in active_rows if f['momentum_class'] == 'momentum-flat']
    buy_signals  = [o for o in market_opps if o['return_1m'] > 4.0]

    benchmark_return = (
        latest_map[BENCHMARK_ISIN].get('return_1m') or 0
        if BENCHMARK_ISIN in latest_map else 0
    )
    benchmark_name = (
        latest_map[BENCHMARK_ISIN].get('name', 'PFA Indeks Globale Aktier')
        if BENCHMARK_ISIN in latest_map else 'PFA Indeks Globale Aktier'
    )

    avg_port_return = (
        sum(active_returns_total) / len(active_returns_total)
        if active_returns_total else 0
    )

    if not TEMPLATE_FILE.exists():
        print(f"❌ Template mangler: {TEMPLATE_FILE}")
        return

    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(
        timestamp            = timestamp,
        week_number          = week_number,
        active_funds         = sorted(active_rows, key=lambda x: x['rank']),
        sold_funds           = sold_rows,
        market_opps          = market_opps,
        sell_signals         = sell_signals,
        buy_signals          = buy_signals,
        trail_stop_alerts    = trail_stop_alerts,   # NY: Trail Stop advarsler
        benchmark_name       = benchmark_name,
        benchmark_return     = round(benchmark_return, 2),
        avg_portfolio_return = round(avg_port_return, 2),
        diff_to_benchmark    = round(avg_port_return - benchmark_return, 2),
        warnings             = validation_warnings,
        total_market_count   = total_market_count,
        trail_stop_pct       = TRAIL_STOP_PCT,      # NY: Sendes til template så tærsklen vises
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    print(f"✅ Deep Dive Rapport færdig (Uge {week_number}).")
    if trail_stop_alerts:
        print(f"   ⚠️  {len(trail_stop_alerts)} trail stop-advarsel(er) i rapporten.")


if __name__ == "__main__":
    build_monthly()
