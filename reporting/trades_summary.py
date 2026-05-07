"""
trades_summary.py
Læser config/trades.json og beregner realiseret afkast, win-rate,
holdperioder, normaliseret afkast pr. måned og segmentanalyse.
Bruges af pfa_build_monthly_report.py og etf_build_monthly.py
"""

import json
import os
from datetime import datetime, date


# ============================================================
# INDLÆSNING
# ============================================================

def load_trades(trades_path="config/trades.json"):
    """Indlæser trades.json. Returnerer tom liste hvis filen ikke findes."""
    if not os.path.exists(trades_path):
        return []
    with open(trades_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# HOLDPERIODE-BEREGNING
# ============================================================

def _holdperiode_dage(dato_str, lukket_dato_str):
    """Beregner antal dage mellem køb og salg."""
    try:
        købt  = datetime.strptime(dato_str, "%Y-%m-%d").date()
        solgt = datetime.strptime(lukket_dato_str, "%Y-%m-%d").date()
        return (solgt - købt).days
    except Exception:
        return None


def _holdperiode_dage_aaben(dato_str):
    """Beregner antal dage en åben position har været holdt."""
    try:
        købt = datetime.strptime(dato_str, "%Y-%m-%d").date()
        return (date.today() - købt).days
    except Exception:
        return None


def _afkast_pr_maaned(afkast_pct, dage):
    """Normaliserer afkast til månedlig rate (30 dage)."""
    if afkast_pct is None or not dage or dage <= 0:
        return None
    return round(afkast_pct / dage * 30, 2)


def _formatér_holdperiode(dage):
    """Formaterer dage til læsbar streng: '142 dage (4.7 mdr)'."""
    if dage is None:
        return "—"
    måneder = round(dage / 30, 1)
    return f"{dage} dage ({måneder} mdr)"


# ============================================================
# HOVED-BEREGNING
# ============================================================

def get_summary(trades, trade_type=None):
    """
    Beregner samlet statistik for handler.

    Args:
        trades: liste fra load_trades()
        trade_type: "PFA", "ETF" eller None (begge)

    Returns dict med alle metrics inkl. holdperioder og segmentanalyse.
    """
    if trade_type:
        trades = [t for t in trades if t.get("type") == trade_type]

    lukkede = [t for t in trades if t.get("status") == "LUKKET"]
    aabne   = [t for t in trades if t.get("status") == "ÅBEN"]

    # Berig lukkede handler med holdperiode og normaliseret afkast
    lukkede_beriget = []
    for t in lukkede:
        dage   = _holdperiode_dage(t.get("dato", ""), t.get("lukket_dato", ""))
        afl_pm = _afkast_pr_maaned(t.get("afkast_pct"), dage)
        lukkede_beriget.append({
            **t,
            "holdperiode_dage": dage,
            "afkast_pr_maaned": afl_pm,
        })

    # Berig åbne handler med dage holdt
    aabne_beriget = []
    for t in aabne:
        dage = _holdperiode_dage_aaben(t.get("dato", ""))
        aabne_beriget.append({
            **t,
            "holdperiode_dage": dage,
        })

    if not lukkede_beriget:
        return {
            "lukkede_handler":       [],
            "aabne_handler":         aabne_beriget,
            "total_realiseret_pct":  None,
            "win_rate":              None,
            "bedste_handel":         None,
            "daarligste_handel":     None,
            "antal_lukket":          0,
            "antal_aabent":          len(aabne_beriget),
            "snit_holdperiode_dage": None,
            "snit_afkast_pr_maaned": None,
            "segment_analyse":       _segment_analyse(lukkede_beriget),
        }

    afkast_liste = [t["afkast_pct"] for t in lukkede_beriget if t.get("afkast_pct") is not None]
    profitable   = [a for a in afkast_liste if a > 0]

    total_realiseret = round(sum(afkast_liste) / len(afkast_liste), 2) if afkast_liste else None
    win_rate         = round(len(profitable) / len(afkast_liste) * 100, 1) if afkast_liste else None

    # Holdperiode snit
    dage_liste = [t["holdperiode_dage"] for t in lukkede_beriget if t["holdperiode_dage"]]
    snit_dage  = round(sum(dage_liste) / len(dage_liste)) if dage_liste else None

    # Normaliseret afkast snit
    afl_pm_liste = [t["afkast_pr_maaned"] for t in lukkede_beriget if t["afkast_pr_maaned"] is not None]
    snit_afl_pm  = round(sum(afl_pm_liste) / len(afl_pm_liste), 2) if afl_pm_liste else None

    sorteret       = sorted(lukkede_beriget, key=lambda t: t.get("afkast_pct", 0))
    bedste         = sorteret[-1] if sorteret else None
    daarligste     = sorteret[0]  if sorteret else None

    return {
        "lukkede_handler":       lukkede_beriget,
        "aabne_handler":         aabne_beriget,
        "total_realiseret_pct":  total_realiseret,
        "win_rate":              win_rate,
        "bedste_handel":         bedste,
        "daarligste_handel":     daarligste,
        "antal_lukket":          len(lukkede_beriget),
        "antal_aabent":          len(aabne_beriget),
        "snit_holdperiode_dage": snit_dage,
        "snit_afkast_pr_maaned": snit_afl_pm,
        "segment_analyse":       _segment_analyse(lukkede_beriget),
    }


def _segment_analyse(lukkede):
    """Beregner win-rate og snit afkast opdelt på PFA vs ETF."""
    segmenter = {}
    for t in lukkede:
        seg = t.get("type", "UKENDT")
        if seg not in segmenter:
            segmenter[seg] = []
        if t.get("afkast_pct") is not None:
            segmenter[seg].append(t["afkast_pct"])

    resultat = {}
    for seg, afkast in segmenter.items():
        if not afkast:
            continue
        profitable = [a for a in afkast if a > 0]
        resultat[seg] = {
            "antal":            len(afkast),
            "win_rate":         round(len(profitable) / len(afkast) * 100, 1),
            "snit_afkast":      round(sum(afkast) / len(afkast), 2),
            "bedste":           max(afkast),
            "daarligste":       min(afkast),
        }
    return resultat


# ============================================================
# FORMAT TIL JINJA2-TEMPLATE
# ============================================================

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
        dage = h.get("holdperiode_dage")
        return {
            "navn":              h.get("navn", ""),
            "afkast":            fmt_pct(h.get("afkast_pct")),
            "købt":              h.get("dato", ""),
            "solgt":             h.get("lukket_dato", ""),
            "positiv":           (h.get("afkast_pct") or 0) > 0,
            "holdperiode":       _formatér_holdperiode(dage),
            "afkast_pr_maaned":  fmt_pct(h.get("afkast_pr_maaned")),
        }

    # Segment-analyse formateret
    segment_fmt = {}
    for seg, data in (summary.get("segment_analyse") or {}).items():
        segment_fmt[seg] = {
            "antal":        data["antal"],
            "win_rate":     f"{data['win_rate']:.0f}%",
            "snit_afkast":  fmt_pct(data["snit_afkast"]),
            "bedste":       fmt_pct(data["bedste"]),
            "daarligste":   fmt_pct(data["daarligste"]),
        }

    # Åbne handler med dage holdt
    aabne_fmt = []
    for t in (summary.get("aabne_handler") or []):
        dage = t.get("holdperiode_dage")
        aabne_fmt.append({
            "navn":        t.get("navn", ""),
            "type":        t.get("type", ""),
            "isin":        t.get("isin", ""),
            "ticker":      t.get("ticker"),
            "købt":        t.get("dato", ""),
            "kurs":        t.get("kurs"),
            "holdperiode": _formatér_holdperiode(dage),
        })

    snit_dage = summary.get("snit_holdperiode_dage")

    return {
        "total_realiseret":      fmt_pct(summary["total_realiseret_pct"]),
        "win_rate":              f"{summary['win_rate']:.0f}%" if summary["win_rate"] is not None else "—",
        "antal_lukket":          summary["antal_lukket"],
        "antal_aabent":          summary["antal_aabent"],
        "snit_holdperiode":      _formatér_holdperiode(snit_dage),
        "snit_afkast_pr_maaned": fmt_pct(summary.get("snit_afkast_pr_maaned")),
        "bedste_handel":         fmt_handel(summary["bedste_handel"]),
        "daarligste_handel":     fmt_handel(summary["daarligste_handel"]),
        "segment_analyse":       segment_fmt,
        "aabne_handler":         aabne_fmt,
        "lukkede_handler": [
            {
                "navn":              t.get("navn", ""),
                "type":              t.get("type", ""),
                "afkast":            fmt_pct(t.get("afkast_pct")),
                "positiv":           (t.get("afkast_pct") or 0) > 0,
                "købt":              t.get("dato", ""),
                "solgt":             t.get("lukket_dato", ""),
                "holdperiode":       _formatér_holdperiode(t.get("holdperiode_dage")),
                "afkast_pr_maaned":  fmt_pct(t.get("afkast_pr_maaned")),
            }
            for t in summary["lukkede_handler"]
        ],
    }


# ============================================================
# TEST — kør: python trades_summary.py
# ============================================================

if __name__ == "__main__":
    trades = load_trades("trades.json")

    print("\n=== ALLE HANDLER ===")
    s = get_summary(trades)
    print(f"Lukkede:                {s['antal_lukket']}")
    print(f"Åbne:                   {s['antal_aabent']}")
    print(f"Snit realiseret:        {s['total_realiseret_pct']}%")
    print(f"Win-rate:               {s['win_rate']}%")
    print(f"Snit holdperiode:       {_formatér_holdperiode(s['snit_holdperiode_dage'])}")
    print(f"Snit afkast pr. mdr:    {s['snit_afkast_pr_maaned']}%")
    if s['bedste_handel']:
        b = s['bedste_handel']
        print(f"Bedste:                 {b['navn']} ({b['afkast_pct']}%) — {_formatér_holdperiode(b['holdperiode_dage'])} — {b['afkast_pr_maaned']}%/mdr")
    if s['daarligste_handel']:
        d = s['daarligste_handel']
        print(f"Dårligste:              {d['navn']} ({d['afkast_pct']}%) — {_formatér_holdperiode(d['holdperiode_dage'])} — {d['afkast_pr_maaned']}%/mdr")

    print(f"\n=== SEGMENT-ANALYSE ===")
    for seg, data in s['segment_analyse'].items():
        print(f"{seg}: {data['antal']} handler · win-rate {data['win_rate']}% · snit {data['snit_afkast']}% · bedste {data['bedste']}% · dårligste {data['daarligste']}%")

    print(f"\n=== ÅBNE POSITIONER ===")
    for t in s['aabne_handler']:
        print(f"  {t['navn']} — holdt {_formatér_holdperiode(t['holdperiode_dage'])}")

    print(f"\n=== TEMPLATE FORMAT (PFA) ===")
    sp  = get_summary(trades, trade_type="PFA")
    fmt = format_for_template(sp)
    print(f"total_realiseret:       {fmt['total_realiseret']}")
    print(f"win_rate:               {fmt['win_rate']}")
    print(f"snit_holdperiode:       {fmt['snit_holdperiode']}")
    print(f"snit_afkast_pr_maaned:  {fmt['snit_afkast_pr_maaned']}")
    print(f"segment_analyse:        {fmt['segment_analyse']}")
    for h in fmt['lukkede_handler']:
        print(f"  {h['navn']}: {h['afkast']} · {h['holdperiode']} · {h['afkast_pr_maaned']}/mdr")
