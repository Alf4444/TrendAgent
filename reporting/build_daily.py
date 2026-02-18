# reporting/build_daily.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "latest.json"
TPL_DIR = ROOT / "templates"
OUT = ROOT / "build" / "daily.html"

def load_latest() -> Dict[str, Any]:
    if not DATA.exists():
        return {"funds": []}
    return json.loads(DATA.read_text(encoding="utf-8"))

def to_danish_number(x: float | None) -> str:
    if x is None:
        return ""
    s = f"{x:0.2f}"
    return s.replace(".", ",")

def normalize_rows(raw_funds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Gør alle de felter templaten kan finde på at spørge efter tilgængelige.
    """
    out: List[Dict[str, Any]] = []
    for r in raw_funds:
        out.append(
            {
                # primære felter
                "isin": r.get("isin") or "",
                "nav": r.get("nav"),  # float eller None
                "nav_raw": r.get("nav_raw") or "",
                "nav_date": r.get("nav_date") or "",  # ISO eller ""
                "nav_date_raw": r.get("nav_date_raw") or "",
                "currency": r.get("currency") or "",
                # felter som nogle templates forventer
                "change_pct": r.get("change_pct", None),
                "event": r.get("event") or "",
                "trend_state": r.get("trend_state") or "",
                # evt. debug
                "stamdata_raw": r.get("stamdata_raw") or {},
            }
        )
    return out

def main() -> None:
    latest = load_latest()
    raw_funds: List[Dict[str, Any]] = latest.get("funds", [])
    rows = normalize_rows(raw_funds)

    # Log lidt i Actions, så vi kan se at vi HAR rækker
    print("[BUILD] Rows prepared:", len(rows))
    for r in rows:
        print(f" - {r['isin']}: NAV={r.get('nav')} NAVDato={r.get('nav_date')}")

    env = Environment(
        loader=FileSystemLoader(str(TPL_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["dknum"] = to_danish_number

    tpl_name = "daily.html.j2"
    tpl_path = TPL_DIR / tpl_name
    OUT.parent.mkdir(parents=True, exist_ok=True)

    if not tpl_path.exists():
        # Simpel fallback hvis templaten mangler
        html_rows = "".join(
            f"<tr><td>{r['isin']}</td><td>{to_danish_number(r['nav'])}</td><td>{r['nav_date']}</td></tr>"
            for r in rows
        )
        html = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Daily</title></head>"
            "<body><h1>Daily</h1><table border='1'><tr><th>ISIN</th><th>NAV</th><th>NAVDato</th></tr>"
            + html_rows
            + "</table></body></html>"
        )
        OUT.write_text(html, encoding="utf-8")
        print(f"[BUILD] Wrote fallback HTML → {OUT}")
        return

    template = env.get_template(tpl_name)

    # Giv templaten flere aliaser (så uanset om den bruger 'funds', 'rows', 'items' eller 'table', virker det)
    context = {
        "funds": rows,
        "rows": rows,
        "items": rows,
        "table": rows,
    }

    html = template.render(**context)
    OUT.write_text(html, encoding="utf-8")
    print(f"[BUILD] Wrote HTML → {OUT}")

if __name__ == "__main__":
    main()
