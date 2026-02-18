# reporting/build_daily.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]  # repo rod
DATA = ROOT / "data" / "latest.json"
TPL_DIR = ROOT / "templates"
OUT = ROOT / "build" / "daily.html"


def load_latest() -> Dict[str, Any]:
    if not DATA.exists():
        # Skriv en minimal tom struktur, så vi altid kan bygge HTML
        return {"funds": []}
    return json.loads(DATA.read_text(encoding="utf-8"))


def to_danish_number(x: float | None) -> str:
    if x is None:
        return ""
    # 2 decimaler og komma som decimaltegn
    s = f"{x:0.2f}"
    return s.replace(".", ",")


def main() -> None:
    latest = load_latest()
    funds: List[Dict[str, Any]] = latest.get("funds", [])

    env = Environment(
        loader=FileSystemLoader(str(TPL_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Gør nogle helper-funktioner og defaults tilgængelige i templaten
    env.filters["dknum"] = to_danish_number

    # Fallback hvis templaten ikke findes (så vi altid leverer en HTML)
    tpl_name = "daily.html.j2"
    tpl_path = TPL_DIR / tpl_name
    if not tpl_path.exists():
        OUT.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for row in funds:
            nav = row.get("nav")
            nav_date = row.get("nav_date") or ""
            isin = row.get("isin") or ""
            rows.append(f"<tr><td>{isin}</td><td>{to_danish_number(nav)}</td><td>{nav_date}</td></tr>")
        html = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Daily</title></head>"
            "<body><h1>Daily</h1><table border='1'><tr><th>ISIN</th><th>NAV</th><th>NAVDato</th></tr>"
            + "".join(rows)
            + "</table></body></html>"
        )
        OUT.write_text(html, encoding="utf-8")
        print(f"[BUILD] Wrote fallback HTML → {OUT}")
        return

    template = env.get_template(tpl_name)

    # Defensiv normalisering for templaten
    norm_funds: List[Dict[str, Any]] = []
    for r in funds:
        norm_funds.append(
            {
                "isin": r.get("isin") or "",
                "nav": r.get("nav"),  # float eller None
                "nav_date": r.get("nav_date") or "",  # ISO eller ""
                "currency": r.get("currency") or "",
                "change_pct": r.get("change_pct") if "change_pct" in r else None,
            }
        )

    html = template.render(funds=norm_funds)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"[BUILD] Wrote HTML → {OUT}")


if __name__ == "__main__":
    main()
