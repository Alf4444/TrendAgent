import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
REPORT_FILE = ROOT / "build/daily.html"

def build_report():
    if not DATA_FILE.exists(): return
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows_html = ""
    for item in data:
        # Hent værdier og håndter manglende data
        nav = item.get("nav") or 0
        ytd = item.get("return_ytd", "0,00").replace(",", ".")
        w1 = item.get("return_1w", "0,00").replace(",", ".")
        m1 = item.get("return_1m", "0,00").replace(",", ".")
        
        # Farvekode funktion
        def get_color_class(val_str):
            try:
                v = float(val_str)
                return "pos" if v > 0 else "neg" if v < 0 else ""
            except: return ""

        # Trend logik (Simpel version indtil MA200 er klar)
        # Hvis 1 uge er bedre end 1 måned, er der positivt momentum
        try:
            trend_val = float(w1) - float(m1)
            if trend_val > 0.5:
                trend_html = '<span class="badge badge-up">STIGENDE ↑</span>'
            elif trend_val < -0.5:
                trend_html = '<span class="badge badge-down">FALDENDE ↓</span>'
            else:
                trend_html = '<span class="badge">NEUTRAL</span>'
        except:
            trend_html = '<span class="badge">INGEN DATA</span>'

        rows_html += f"""
        <tr>
            <td>
                <strong>{item.get('name', item['isin'])}</strong><br>
                <small style="color: #666;">{item['isin']}</small>
            </td>
            <td style="font-family: monospace; font-weight: bold;">{nav:,.22f}</td>
            <td class="{get_color_class(ytd)}">{ytd}%</td>
            <td class="{get_color_class(w1)}">{w1}%</td>
            <td class="{get_color_class(m1)}">{m1}%</td>
            <td>{trend_html}</td>
            <td><a href="{item.get('url', '#')}" class="pdf-link" target="_blank">PDF ↗</a></td>
        </tr>
        """

    html_template = f"""
    <!doctype html>
    <html lang="da">
    <head>
        <meta charset="utf-8">
        <title>TrendAgent Pro</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 40px; background: #f8f9fa; color: #333; }}
            h1 {{ color: #1a73e8; margin-bottom: 5px; }}
            .subtitle {{ color: #666; margin-bottom: 30px; }}
            table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.05); }}
            th {{ background: #1a73e8; color: white; padding: 15px; text-align: left; font-size: 13px; text-transform: uppercase; }}
            td {{ padding: 15px; border-bottom: 1px solid #edf2f7; }}
            tr:hover {{ background: #f1f8ff; }}
            .pos {{ color: #28a745; font-weight: bold; }}
            .neg {{ color: #d93025; font-weight: bold; }}
            .badge {{ padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; background: #e8eaed; color: #5f6368; }}
            .badge-up {{ background: #e6f4ea; color: #1e8e3e; }}
            .badge-down {{ background: #fce8e6; color: #d93025; }}
            .pdf-link {{ text-decoration: none; color: #1a73e8; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>TrendAgent Dashboard</h1>
        <p class="subtitle">Opdateret: {datetime.now().strftime('%d. %b %Y kl. %H:%M')}</p>
        <table>
            <thead>
                <tr>
                    <th>Investering</th>
                    <th>Kurs (NAV)</th>
                    <th>ÅTD</th>
                    <th>1 Uge</th>
                    <th>1 Md</th>
                    <th>Trend</th>
                    <th>Faktaark</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_template, encoding="utf-8")

if __name__ == "__main__":
    build_report()
