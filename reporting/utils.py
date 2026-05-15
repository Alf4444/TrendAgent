"""
utils.py — Fælles tekniske hjælpefunktioner til TrendAgent
===========================================================
Bruges af pfa_build_daily_report.py, pfa_build_weekly_report.py og
pfa_build_monthly_report.py så alle tre rapporter bruger
præcis samme beregningslogik.
"""

import statistics
from datetime import datetime


# ==========================================
# GLIDENDE GENNEMSNIT (MA)
# ==========================================

def get_ma(prices, window):
    """
    Beregner Simple Moving Average (SMA) for de seneste 'window' datapunkter.
    Returnerer None hvis der ikke er nok data eller data indeholder None-værdier.
    """
    if not isinstance(prices, list) or len(prices) < window:
        return None
    relevant = [p for p in prices[-window:] if p is not None]
    if len(relevant) < window:
        return None
    return round(sum(relevant) / window, 2)


def get_best_ma(prices):
    """
    Returnerer det bedste tilgængelige glidende gennemsnit og dets label.
    Prioritering: MA200 > MA50 > MA20.

    Baggrund: Historik opbygges gradvist fra daglige kørsler.
    MA200 kræver ~9 måneder. Indtil da bruges MA50 eller MA20 som
    fallback så trend-visning ikke er tom for alle fonde fra start.

    Returnerer: (ma_værdi, label) fx (412.5, "MA200") eller (None, None)
    """
    for window, label in [(200, "MA200"), (50, "MA50"), (20, "MA20")]:
        ma = get_ma(prices, window)
        if ma is not None:
            return ma, label
    return None, None


# ==========================================
# RSI — RELATIVE STRENGTH INDEX
# ==========================================

def get_rsi(prices, window=14):
    """
    Beregner Relative Strength Index (RSI) over 'window' perioder.
    Returnerer None hvis der ikke er nok data.

    Tolkning:
      > 70 = overkøbt (potentielt salgssignal)
      < 30 = oversolgt (potentielt købssignal)
    """
    if not isinstance(prices, list) or len(prices) <= window:
        return None

    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    recent = deltas[-window:]

    gains  = [d if d > 0 else 0 for d in recent]
    losses = [abs(d) if d < 0 else 0 for d in recent]

    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


# ==========================================
# VOLATILITET
# ==========================================

def get_volatility(prices, window=20):
    """
    Beregner historisk volatilitet som standardafvigelse af daglige
    procentvise ændringer over 'window' perioder.
    Returnerer None hvis der ikke er nok data.

    Bruges i daily-rapporten til at vise fondenes risikoprofil.
    """
    if not isinstance(prices, list) or len(prices) < window + 1:
        return None

    relevant = prices[-(window + 1):]
    pct_changes = [
        (relevant[i] - relevant[i-1]) / relevant[i-1] * 100
        for i in range(1, len(relevant))
        if relevant[i-1] != 0
    ]

    if len(pct_changes) < 2:
        return None

    return round(statistics.stdev(pct_changes), 2)


# ==========================================
# DRAWDOWN
# ==========================================

def calculate_drawdown(prices):
    """
    Beregner aktuelt fald fra All-Time High (ATH) i den tilgængelige historik.
    Returnerer negativ procent (fx -12.5 betyder 12.5% under ATH).
    Returnerer 0.0 hvis ingen data.
    """
    if not prices:
        return 0.0

    ath = max(prices)
    if ath == 0:
        return 0.0

    return round(((prices[-1] / ath) - 1) * 100, 2)


# ==========================================
# ÅTD — YEAR TO DATE
# ==========================================

def calculate_ytd(prices_dict):
    """
    Beregner afkast siden årets start (Year-To-Date) fra historikken.
    Finder seneste kurs fra 31. december forrige år som startpunkt.

    OBS: Bruges som supplement til den officielle return_ytd fra PFA
    faktaarket. Den officielle værdi foretrækkes når den er tilgængelig.
    """
    if not prices_dict:
        return 0.0

    dates = sorted(prices_dict.keys())
    cur_year = datetime.now().year
    start_price = None

    # Seneste kurs fra forrige år
    for d in reversed(dates):
        if d < f"{cur_year}-01-01":
            start_price = prices_dict[d]
            break

    # Backup: første kurs i år
    if start_price is None:
        for d in dates:
            if d.startswith(str(cur_year)):
                start_price = prices_dict[d]
                break

    if not start_price or start_price == 0:
        return 0.0

    current_price = prices_dict[dates[-1]]
    return round(((current_price / start_price) - 1) * 100, 2)


# ==========================================
# MA CROSS — GOLDEN / DEATH CROSS
# ==========================================

def get_cross_signal(prices):
    """
    Detekterer MA20/MA50 kryds-signaler.

    Golden Cross: MA20 krydser op over MA50 → positivt momentum-signal
    Death Cross:  MA20 krydser ned under MA50 → negativt momentum-signal

    Returnerer én af: "🚀 GOLDEN", "💀 DEATH", "–"
    Kræver mindst 51 datapunkter for at kunne beregne begge MA-værdier.
    """
    if not isinstance(prices, list) or len(prices) < 51:
        return "–"

    ma20_nu   = get_ma(prices, 20)
    ma50_nu   = get_ma(prices, 50)
    ma20_prev = get_ma(prices[:-1], 20)
    ma50_prev = get_ma(prices[:-1], 50)

    if not all([ma20_nu, ma50_nu, ma20_prev, ma50_prev]):
        return "–"

    if ma20_prev <= ma50_prev and ma20_nu > ma50_nu:
        return "🚀 GOLDEN"
    elif ma20_prev >= ma50_prev and ma20_nu < ma50_nu:
        return "💀 DEATH"

    return "–"


# ==========================================
# TREND SHIFT
# ==========================================

def get_trend_state(prices):
    """
    Beregner nuværende trend-tilstand baseret på bedste tilgængelige MA.
    Returnerer: "BULL", "BEAR" eller "WARM-UP" (ikke nok data endnu)
    """
    if not prices:
        return "WARM-UP"

    ma_val, _ = get_best_ma(prices)
    if ma_val is None:
        return "WARM-UP"

    return "BULL" if prices[-1] > ma_val else "BEAR"


def get_trend_shift(prices, prev_trend_state):
    """
    Sammenligner nuværende trend med den forrige kendte trend-tilstand.
    Bruges til at detektere om en fond har skiftet fra BULL→BEAR eller BEAR→BULL.

    Returnerer:
      "BULL→BEAR"  hvis fonden netop er skiftet til BEAR
      "BEAR→BULL"  hvis fonden netop er skiftet til BULL
      None         hvis ingen skift

    prev_trend_state: Gemt tilstand fra forrige kørsel (str eller None)
    """
    current = get_trend_state(prices)

    if prev_trend_state is None or prev_trend_state == "WARM-UP":
        return None

    if prev_trend_state == "BULL" and current == "BEAR":
        return "BULL→BEAR"
    elif prev_trend_state == "BEAR" and current == "BULL":
        return "BEAR→BULL"

    return None


# ==========================================
# TRAIL STOP — HIGH WATER MARK
# ==========================================

def days_since_hwm(hwm_date_str):
    """
    Beregner antal dage siden High Water Mark blev sat.
    Returnerer None hvis datoen ikke kan parses.
    """
    try:
        hwm_date = datetime.strptime(hwm_date_str, '%Y-%m-%d')
        return (datetime.now() - hwm_date).days
    except Exception:
        return None


def check_trail_stop(isin, curr_price, buy_price, hwm_data, today_str, trail_pct=3.0):
    """
    Opdaterer High Water Mark og returnerer en trail stop-advarsel
    hvis fonden er faldet mere end trail_pct % fra sit toppunkt.

    Logik:
      1. Initialisér HWM til buy_price hvis ingen historik
      2. Ny top → opdater HWM og hwm_date
      3. Fald fra HWM > trail_pct → returner advarsel-dict

    Returnerer: (opdateret hwm_entry, alert_dict_eller_None)
    """
    entry    = hwm_data.get(isin, {})
    hwm      = entry.get("hwm", buy_price)
    hwm_date = entry.get("hwm_date", today_str)

    # Ny top?
    if curr_price > hwm:
        hwm      = curr_price
        hwm_date = today_str
        entry    = {"hwm": round(hwm, 2), "hwm_date": hwm_date}

    fall_pct = ((curr_price / hwm) - 1) * 100 if hwm > 0 else 0.0

    alert = None
    if fall_pct <= -trail_pct:
        alert = {
            "isin":      isin,
            "hwm":       round(hwm, 2),
            "hwm_date":  hwm_date,
            "days_hwm":  days_since_hwm(hwm_date),
            "curr":      round(curr_price, 2),
            "fall_pct":  round(fall_pct, 2),
            "buy_price": round(buy_price, 2),
            "total_ret": round(((curr_price / buy_price) - 1) * 100, 2) if buy_price else 0,
        }

    return entry, alert


# ==========================================
# HANDELSDAGE
# ==========================================

def is_trading_day(date_str):
    """
    Returnerer True hvis dato-strengen (YYYY-MM-DD) er en hverdag (man-fre).
    Bruges til at filtrere weekender fra historikken før teknisk analyse.
    OBS: Helligdage filtreres ikke — PFA leverer ikke data disse dage,
    så de vil alligevel ikke være i historikken.
    """
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.weekday() < 5
    except Exception:
        return False


# ==========================================
# MOMENTUM OG TREND VELOCITY (monthly)
# ==========================================

def get_trend_velocity(return_1w, return_1m):
    """
    Sammenligner ugens afkast mod månedens gennemsnit per uge.
    Bruges i monthly-rapporten til at vise om momentum accelererer eller bremser.

    Returnerer: (label, css_class)
    """
    r1w = return_1w or 0
    r1m = return_1m or 0
    avg_weekly = r1m / 4

    if r1w > avg_weekly and r1w > 0:
        return "🚀 Accelererer", "trend-up"
    elif r1w < avg_weekly:
        return "📉 Bremser", "trend-down"
    return "➡️ Stabil", "trend-side"


def get_momentum_status(return_1m, rank, total_funds=47):
    """
    Klassificerer en fonds momentum baseret på markedsrang og 1M afkast.
    Bruges i monthly-rapporten.

    Returnerer: (label, css_class)
    """
    r1m = return_1m or 0

    if rank > 10:
        return "🛑 Outperformed", "momentum-flat"
    if r1m < 0 or rank > 7:
        return "⚠️ Slower", "momentum-slow"
    if rank <= 5 and r1m > 0:
        return "🚀 Top Performer", "momentum-fast"
    return "✅ Stabil", "momentum-stable"


def get_trail_stop_pct(volatility):
    """
    Beregner variabelt Trail Stop baseret på fondens volatilitet.
    Enkelt kilde til sandhed — bruges af etf_build_weekly.py og etf_send_alert.py.

    Volatilitet er 20-dages standardafvigelse af daglige afkast i %.
      < 1.0%  → 3% stop  (fx obligationer, lav-vol fonde)
      1-2%    → 5% stop  (fx brede aktieindeks)
      > 2.0%  → 7% stop  (fx Korea, Hydrogen, Halvledere)
    """
    if volatility is None:
        return 3.0
    if volatility < 1.0:
        return 3.0
    elif volatility < 2.0:
        return 5.0
    else:
        return 7.0
