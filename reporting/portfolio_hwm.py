"""
portfolio_hwm.py
Tracker porteføljens samlede afkast over tid og beregner drawdown fra peak.
Gemmer historik i data/portfolio_hwm.json.
Bruges af pfa_build_monthly_report.py og etf_build_monthly.py
"""

import json
import os
from datetime import datetime


# ============================================================
# BOOTSTRAP DATA — kendte historiske datapunkter
# Beregnet fra trades.json + pfa_hwm.json ved session 14
# ============================================================

PFA_BOOTSTRAP = [
    # (dato, afkast_pct) — estimerede portefølje-afkast på nøgle-datoer
    # 2026-02-23: Lazard købt — startpunkt for porteføljen
    {"dato": "2026-02-23", "afkast": 0.0,  "note": "Lazard købt — portefølje start"},
    # 2026-03-02: C WorldWide + Sydinvest købt
    {"dato": "2026-03-02", "afkast": 1.5,  "note": "C WorldWide + Sydinvest købt (estimeret)"},
    # 2026-05-07: HWM-dato for alle 4 fonde — beregnet fra hwm vs købt kurs
    {"dato": "2026-05-07", "afkast": 8.21, "note": "Bootstrap fra pfa_hwm.json (Lazard +6.7%, CWW +14.3%, Syn +9.8%, Rob +2.0%)"},
]

ETF_BOOTSTRAP = [
    # 2026-05-05: Begge ETF'er købt — startpunkt
    {"dato": "2026-05-05", "afkast": 0.0, "note": "VVSM + FLXK købt — ETF portefølje start"},
]


# ============================================================
# INDLÆSNING OG GEMNING
# ============================================================

def load_portfolio_hwm(path):
    """Indlæser portfolio_hwm.json. Bootstrapper hvis filen ikke eksisterer."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Første kørsel — bootstrap med kendte datapunkter
    return {
        "pfa": {
            "peak_afkast":  8.21,
            "peak_dato":    "2026-05-07",
            "historik":     PFA_BOOTSTRAP.copy(),
        },
        "etf": {
            "peak_afkast":  0.0,
            "peak_dato":    "2026-05-05",
            "historik":     ETF_BOOTSTRAP.copy(),
        }
    }


def save_portfolio_hwm(data, path):
    """Gemmer portfolio_hwm.json."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# OPDATER OG BEREGN
# ============================================================

def update_and_get_drawdown(portfolio_hwm, segment, today_str, current_afkast):
    """
    Opdaterer historik for et segment (pfa/etf) og beregner drawdown.

    Args:
        portfolio_hwm: dict fra load_portfolio_hwm()
        segment: "pfa" eller "etf"
        today_str: dato i format YYYY-MM-DD
        current_afkast: float — dagens porteføljeafkast i %

    Returns:
        dict med drawdown-data klar til template
    """
    seg = portfolio_hwm.setdefault(segment, {
        "peak_afkast": current_afkast,
        "peak_dato":   today_str,
        "historik":    []
    })

    # Tilføj dagens punkt hvis ikke allerede der
    historik = seg.get("historik", [])
    datoer   = [h["dato"] for h in historik]
    if today_str not in datoer:
        historik.append({
            "dato":   today_str,
            "afkast": round(current_afkast, 2)
        })
        seg["historik"] = historik

    # Opdater peak
    if current_afkast > seg.get("peak_afkast", -999):
        seg["peak_afkast"] = round(current_afkast, 2)
        seg["peak_dato"]   = today_str

    peak       = seg["peak_afkast"]
    peak_dato  = seg["peak_dato"]
    drawdown   = round(current_afkast - peak, 2)

    # Beregn dage siden peak
    try:
        p_dato = datetime.strptime(peak_dato, "%Y-%m-%d")
        i_dag  = datetime.strptime(today_str, "%Y-%m-%d")
        dage_siden_peak = (i_dag - p_dato).days
    except Exception:
        dage_siden_peak = 0

    # Sorter historik kronologisk og behold maks 24 punkter
    seg["historik"] = sorted(historik, key=lambda x: x["dato"])[-24:]

    return {
        "aktuel_afkast":    round(current_afkast, 2),
        "peak_afkast":      peak,
        "peak_dato":        peak_dato,
        "drawdown":         drawdown,
        "dage_siden_peak":  dage_siden_peak,
        "er_ved_peak":      drawdown >= -0.1,
        "historik":         seg["historik"],
    }


# ============================================================
# FORMAT TIL TEMPLATE
# ============================================================

def format_drawdown_for_template(dd):
    """Formaterer drawdown-dict til Jinja2-template."""
    if not dd:
        return None

    def fmt(v):
        if v is None:
            return "—"
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.2f}%"

    return {
        "aktuel":          fmt(dd["aktuel_afkast"]),
        "peak":            fmt(dd["peak_afkast"]),
        "peak_dato":       dd["peak_dato"],
        "drawdown":        fmt(dd["drawdown"]),
        "drawdown_raw":    dd["drawdown"],
        "dage_siden_peak": dd["dage_siden_peak"],
        "er_ved_peak":     dd["er_ved_peak"],
        "advarsel":        dd["drawdown"] <= -5.0,
        "historik":        dd["historik"],
    }
