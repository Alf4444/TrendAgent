"""
trades_summary.py
Læser config/trades.json og beregner realiseret afkast, win-rate og statistik.
Bruges af pfa_build_monthly_report.py og etf_build_monthly.py
"""

import json
import os
from datetime import datetime


def load_trades(trades_path="config/trades.json"):
    """Indlæser trades.json. Returnerer tom liste hvis filen ikke findes."""
    if not os.path.exists(trades_path):
        return []
    with open(trades_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_summary(trades, trade_type=None):
    """
    Beregner samlet statistik for handler.

    Args:
        trades: liste fra load_trades()
        trade_type: "PFA", "ETF" eller None (begge)

    Returns dict med:
        - lukkede_handler: liste af lukkede positioner
        - aabne_handler: liste af åbne positioner
        - total_realiseret_pct: gennemsnitligt afkast på lukkede handler
        - win_rate: andel profitable lukkede handler (%)
        - bedste_handel: dict
        - daarligste_handel: dict
        - antal_lukket: int
        - antal_aabent: int
    """
    if trade_type:
        trades = [t for t in trades if t.get("type") == trade_type]

    lukkede = [t for t in trades if t.get("status") == "LUKKET"]
    aabne   = [t for t in trades if t.get("status") == "ÅBEN"]

    if not lukkede:
        return {
            "lukkede_handler": [],
            "aabne_handler": aabne,
            "total_realiseret_pct": None,
            "win_rate": None,
            "bedste_handel": None,
            "daarligste_handel": None,
            "antal_lukket": 0,
            "antal_aabent": len(aabne),
        }

    afkast_liste = [t["afkast_pct"] for t in lukkede if t.get("afkast_pct") is not None]
    profitable   = [a for a in afkast_liste if a > 0]

    total_realiseret = round(sum(afkast_liste) / len(afkast_liste), 2) if afkast_liste else None
    win_rate         = round(len(profitable) / len(afkast_liste) * 100, 1) if afkast_liste else None

    sorteret = sorted(lukkede, key=lambda t: t.get("afkast_pct", 0))
    bedste      = sorteret[-1] if sorteret else None
    daarligste  = sorteret[0]  if sorteret else None

    return {
        "lukkede_handler": lukkede,
        "aabne_handler": aabne,
        "total_realiseret_pct": total_realiseret,
        "win_rate": win_rate,
        "bedste_handel": bedste,
        "daarligste_handel": daarligste,
        "antal_lukket": len(lukkede),
        "antal_aabent": len(aabne),
    }


def format_for_template(summary):
    """
    Konverterer summary til et dict klar til Jinja2-template.
    Alle tal er formaterede strenge.
    """
    if not summary:
        return {}

    def fmt_pct(v):
        if v is None:
            return "—"
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.1f}%"

    def fmt_handel(h):
        if not h:
            return None
        return {
            "navn": h.get("navn", ""),
            "afkast": fmt_pct(h.get("afkast_pct")),
            "købt": h.get("dato", ""),
            "solgt": h.get("lukket_dato", ""),
            "positiv": (h.get("afkast_pct") or 0) > 0,
        }

    return {
        "total_realiseret":  fmt_pct(summary["total_realiseret_pct"]),
        "win_rate":          f"{summary['win_rate']:.0f}%" if summary["win_rate"] is not None else "—",
        "antal_lukket":      summary["antal_lukket"],
        "antal_aabent":      summary["antal_aabent"],
        "bedste_handel":     fmt_handel(summary["bedste_handel"]),
        "daarligste_handel": fmt_handel(summary["daarligste_handel"]),
        "lukkede_handler": [
            {
                "navn":    t.get("navn", ""),
                "type":    t.get("type", ""),
                "afkast":  fmt_pct(t.get("afkast_pct")),
                "positiv": (t.get("afkast_pct") or 0) > 0,
                "købt":    t.get("dato", ""),
                "solgt":   t.get("lukket_dato", ""),
            }
            for t in summary["lukkede_handler"]
        ],
    }


if __name__ == "__main__":
    # Hurtig test — kør: python trades_summary.py
    trades = load_trades("trades.json")  # lokal sti til test
    print(f"\n=== ALLE HANDLER ===")
    s = get_summary(trades)
    print(f"Lukkede:           {s['antal_lukket']}")
    print(f"Åbne:              {s['antal_aabent']}")
    print(f"Snit realiseret:   {s['total_realiseret_pct']}%")
    print(f"Win-rate:          {s['win_rate']}%")
    if s['bedste_handel']:
        print(f"Bedste:            {s['bedste_handel']['navn']} ({s['bedste_handel']['afkast_pct']}%)")
    if s['daarligste_handel']:
        print(f"Dårligste:         {s['daarligste_handel']['navn']} ({s['daarligste_handel']['afkast_pct']}%)")

    print(f"\n=== PFA HANDLER ===")
    sp = get_summary(trades, trade_type="PFA")
    print(f"Lukkede PFA:       {sp['antal_lukket']}")
    print(f"Snit realiseret:   {sp['total_realiseret_pct']}%")

    print(f"\n=== ETF HANDLER ===")
    se = get_summary(trades, trade_type="ETF")
    print(f"Lukkede ETF:       {se['antal_lukket']}")
