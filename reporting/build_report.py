# reporting/build_report.py
"""
Bygger HTML-rapporter via Jinja2.

Eksempler:
python reporting/build_report.py --kind daily --data latest.json --template templates/daily.html.j2 --out build/daily.html
python reporting/build_report.py --kind weekly --data latest.json --template templates/weekly.html.j2 --out build/weekly.html
"""

import argparse
import json
import os
from datetime import date
from jinja2 import Environment, FileSystemLoader, select_autoescape

def ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def build_context(kind, data):
    # data forventes at have { "rows": [...], "run_date": "YYYY-MM-DD" }
    rows = data.get("rows", [])
    run_date = data.get("run_date") or date.today().isoformat()

    if kind == "daily":
        ctx = {"rows": rows, "run_date": run_date}
    elif kind == "weekly":
        # mock: samme data; i praksis leveres week_change_pct, ytd_return, drawdown m.v. fra modellen
        top_sorted = sorted(rows, key=lambda r: r.get("week_change_pct", 0.0), reverse=True)
        ctx = {
            "rows": rows,
            "week_label": f"{date.today().isocalendar().week}",
            "week_end_date": run_date,
            "top_up": top_sorted[:5],
            "top_down": list(reversed(top_sorted))[:5],
        }
    else:
        raise ValueError("Unknown kind")
    return ctx

def render_html(template_path, context):
    env = Environment(
        loader=FileSystemLoader(searchpath="."),
        autoescape=select_autoescape(["html", "xml"])
    )
    template = env.get_template(template_path)
    return template.render(**context)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["daily", "weekly"], required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = load_json(args.data)
    ctx = build_context(args.kind, data)
    html = render_html(args.template, ctx)

    ensure_dir(args.out)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {args.out}")

if __name__ == "__main__":
    main()
