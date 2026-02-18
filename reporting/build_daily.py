# reporting/build_daily.py
import json, os, pathlib, math, datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "latest.json"
OUT = ROOT / "build" / "daily.html"
OUT.parent.mkdir(parents=True, exist_ok=True)

def dk_number(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    # 1234.56 -> "1.234,56"
    s = f"{float(x):,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s

def load_funds():
    if not DATA.exists():
        return []
    obj = json.loads(DATA.read_text(encoding="utf-8"))
    # accepter både {"funds":[...]} og bare [...]
    funds = obj.get("funds", obj if isinstance(obj, list) else [])
    norm = []
    for f in funds:
        # Normaliser felter
        isin = f.get("isin") or ""
        pfa = f.get("pfa_code") or f.get("id") or ""
        disp_id = isin or pfa  # brug PFA-kode hvis ISIN ikke findes
        nav = f.get("nav")
        nav_date = f.get("nav_date") or ""
        name = f.get("name") or ""
        currency = f.get("currency") or ""
        norm.append({
            "id": disp_id,
            "name": name,
            "nav": nav,
            "nav_date": nav_date,
            "currency": currency
        })
    return norm

def render_html(rows):
    today = datetime.date.today().isoformat()
    head = """<!doctype html>
<html lang="da">
<head>
<meta charset="utf-8" />
<title>TrendAgent – Daglig rapport</title>
<style>
 body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }
 h1 { margin-bottom: 0; }
 small { color: #666; }
 table { border-collapse: collapse; width: 100%; margin-top: 16px; }
 th, td { border: 1px solid #ddd; padding: 8px; font-size: 14px; }
 th { background: #f7f7f7; text-align: left; }
 .badge { padding: 2px 6px; border-radius: 6px; font-size: 12px; }
 .b-neutral { background: #999; color: #fff; }
</style>
</head>
<body>
<h1>TrendAgent – Daglig rapport</h1>
<small>Kørselsdato: %s</small>
<h2>Events</h2>
<p>Fokuser på rækker med <b>trend_shift</b> eller <b>cross_20_50</b>, samt outliers (±3%).</p>
<table>
<thead>
<tr>
  <th>ISIN</th>
  <th>Navn</th>
  <th>NAV</th>
  <th>NAVDato</th>
  <th>Valuta</th>
  <th>1D ændring %</th>
  <th>Event</th>
  <th>trend_state</th>
</tr>
</thead>
<tbody>
""" % today

    trs = []
    for r in rows:
        td_id = r["id"]
        td_name = r["name"]
        td_nav = dk_number(r["nav"])
        td_date = r["nav_date"]
        td_cur = r["currency"]
        td_chg = "0.00%"   # placeholder (kommer fra model senere)
        td_evt = ""
        td_trend = '<span class="badge b-neutral">NEUTRAL</span>'
        trs.append(f"<tr><td>{td_id}</td><td>{td_name}</td><td>{td_nav}</td><td>{td_date}</td><td>{td_cur}</td><td>{td_chg}</td><td>{td_evt}</td><td>{td_trend}</td></tr>")

    tail = """
</tbody>
</table>
<p style="margin-top:16px;color:#666">
Note: Første milepæl bruger default-felter for ændring/event; MA20/50/200 m.m. kommer fra modellen i næste trin.
</p>
</body>
</html>
"""
    return head + "\n".join(trs) + tail

def main():
    rows = load_funds()
    html = render_html(rows)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} with {len(rows)} rows")

if __name__ == "__main__":
    main()
