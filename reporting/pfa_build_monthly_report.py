import json
import sys
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# Tilføj reporting/ til Python-stien så utils.py kan importeres
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    get_ma, get_best_ma, get_rsi,
    get_trend_velocity, get_momentum_status,
    get_cross_signal, get_trend_state, get_trend_shift,
    check_trail_stop, is_trading_day,
)
from trades_summary import load_trades, get_summary, format_for_template
from portfolio_hwm import load_portfolio_hwm, save_portfolio_hwm, update_and_get_drawdown, format_drawdown_for_template
from sector_heatmap import build_heatmap, get_concentration_warning

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
DATA_FILE          = ROOT / "data/pfa_latest.json"
HISTORY_FILE       = ROOT / "data/pfa_history.json"
PORTFOLIO_FILE     = ROOT / "config/pfa_portfolio.json"
TEMPLATE_FILE      = ROOT / "templates/pfa_monthly.html.j2"
REPORT_FILE        = ROOT / "build/pfa_monthly.html"
HWM_FILE           = ROOT / "data/pfa_hwm.json"
TRADES_FILE        = ROOT / "config/trades.json"
PORTFOLIO_HWM_FILE = ROOT / "data/portfolio_hwm.json"

BENCHMARK_ISIN = "PFA000002233"
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
# HJÆLPEFUNKTIONER (monthly-specifikke)
# ==========================================

def get_ranking_data(latest_list):
    """Rangerer alle fonde efter 1M afkast. Returnerer rank_map og total antal."""
    sorted_list = sorted(latest_list, key=lambda x: x.get('return_1m') or -999, reverse=True)
    rank_map = {item['isin']: index + 1 for index, item in enumerate(sorted_list)}
    return rank_map, len(sorted_list)


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

    now          = datetime.now()
    today_str    = now.strftime('%Y-%m-%d')
    timestamp    = now.strftime('%d-%m-%Y %H:%M')
    week_number  = now.strftime('%V')

    hwm_data = load_high_water_marks()

    active_rows          = []
    sold_rows            = []
    active_returns_total = []
    trail_stop_alerts    = []

    for isin, p_info in portfolio.items():
        if isin not in latest_map:
            continue

        official  = latest_map[isin]
        rank      = rank_map.get(isin, 99)
        curr_p    = official.get('nav') or 0
        buy_p     = p_info.get('buy_price', 0)
        is_active = p_info.get('active', False)

        total_return = round(((curr_p - buy_p) / buy_p * 100), 2) if buy_p > 0 else 0

        # MA & RSI fra historik — kun handelsdage
        p_dict = history.get(isin, {})
        sorted_dates = [d for d in sorted(p_dict.keys()) if is_trading_day(d)]
        prices = [p_dict[d] for d in sorted_dates]

        # Sikr dagens NAV er med
        if not prices or prices[-1] != curr_p:
            prices.append(curr_p)

        rsi_val          = get_rsi(prices, 14)
        ma_val, ma_label = get_best_ma(prices)

        # Trend shift — sammenligner med gemt tilstand fra HWM-filen
        prev_trend = hwm_data.get(isin, {}).get('trend_state')
        t_state    = get_trend_state(prices)
        trend_shift = get_trend_shift(prices, prev_trend)

        # Gem nuværende trend_state til næste kørsel
        if isin in hwm_data:
            hwm_data[isin]['trend_state'] = t_state
        else:
            hwm_data[isin] = {'trend_state': t_state}

        # utils.py: get_trend_velocity og get_momentum_status tager værdier direkte
        t_label, t_class = get_trend_velocity(
            official.get('return_1w') or 0,
            official.get('return_1m') or 0,
        )
        m_label, m_class = get_momentum_status(
            official.get('return_1m') or 0,
            rank,
        )

        t_state = "BULL" if (ma_val and curr_p > ma_val) else "BEAR" if ma_val else "N/A"

        fund_data = {
            "isin":           isin,
            "name":           p_info.get('name', isin),
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
            "trend_shift":    trend_shift,   # fx "BULL→BEAR" eller None
            "is_active":      is_active,
        }

        if is_active:
            active_rows.append(fund_data)
            active_returns_total.append(total_return)

            # Trail Stop check via utils.py
            hwm_entry, alert = check_trail_stop(
                isin, curr_p, buy_p, hwm_data, today_str, TRAIL_STOP_PCT
            )
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

    # Gem opdaterede HWM (deles med daily og weekly)
    save_high_water_marks(hwm_data)

    # --- TOP 5 MARKEDSMULIGHEDER ---
    unsorted_opps = [
        i for i in latest_list
        if i['isin'] not in portfolio or not portfolio[i['isin']].get('active', False)
    ]
    sorted_opps = sorted(unsorted_opps, key=lambda x: x.get('return_1m') or 0, reverse=True)[:5]
    market_opps = []
    for o in sorted_opps:
        t_label_o, _ = get_trend_velocity(
            o.get('return_1w') or 0,
            o.get('return_1m') or 0,
        )
        market_opps.append({
            "name":        o.get('name', o['isin']),
            "return_1m":   o.get('return_1m') or 0,
            "return_ytd":  o.get('return_ytd') or 0,
            "rank":        rank_map.get(o['isin']),
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

    # --- HANDELSHISTORIK ---
    trades      = load_trades(str(TRADES_FILE))
    pfa_summary = get_summary(trades, trade_type="PFA")
    trades_data = format_for_template(pfa_summary)

    # --- PORTEFØLJE DRAWDOWN ---
    portfolio_hwm = load_portfolio_hwm(str(PORTFOLIO_HWM_FILE))
    dd_raw = update_and_get_drawdown(portfolio_hwm, "pfa", today_str, round(avg_port_return, 2))
    save_portfolio_hwm(portfolio_hwm, str(PORTFOLIO_HWM_FILE))
    drawdown_data = format_drawdown_for_template(dd_raw)

    # --- SEKTOR HEATMAP ---
    heatmap_data    = build_heatmap(portfolio, active_rows)
    heatmap_warning = get_concentration_warning(heatmap_data)

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
        trail_stop_alerts    = trail_stop_alerts,
        benchmark_name       = benchmark_name,
        benchmark_return     = round(benchmark_return, 2),
        avg_portfolio_return = round(avg_port_return, 2),
        diff_to_benchmark    = round(avg_port_return - benchmark_return, 2),
        warnings             = validation_warnings,
        total_market_count   = total_market_count,
        trail_stop_pct       = TRAIL_STOP_PCT,
        trades_data          = trades_data,
        drawdown_data        = drawdown_data,
        heatmap_data         = heatmap_data,
        heatmap_warning      = heatmap_warning,
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    print(f"✅ Deep Dive Rapport færdig (Uge {week_number}).")
    if trail_stop_alerts:
        print(f"   ⚠️  {len(trail_stop_alerts)} trail stop-advarsel(er) i rapporten.")


if __name__ == "__main__":
    build_monthly()
