import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
REPORT_FILE = ROOT / "build/daily.html"
README_FILE = ROOT / "README.md"

def build_report():
    if not DATA_FILE.exists(): 
        print("Fandt ingen data/latest.json")
        return
        
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Funktion til at håndtere procenter sikkert ved sortering
    def parse_pct(val):
        try: 
            return float(str(val).replace(",", ".").replace("%", ""))
        except: 
            return -99.0

    # Sorter listen så dem med højest ÅTD afkast ligger øverst
    sorted_data = sorted(data, key=lambda x: parse_pct(x.get("return_ytd", 0)), reverse=True)

    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    # --- START README GENERERING ---
    readme_content = f"# 📈 TrendAgent Dashboard\n"
    readme_content += f"**Sidst opdateret:** {timestamp} (Data fra PFA)\n\n"
    readme_content += "### 📊 Aktuel Status\n"
    readme_content += "| Fond | Kurs (NAV) | ÅTD | Trend |\n| :--- | :--- | :--- | :--- |\n"

    rows_html = ""
    for item in sorted_data:
        nav = item.get("nav", 0)
        # Tvinger 2 decimaler og tusindtalsseparator (f.eks. 1.250,50)
        nav_display = "{:,.2f}".format(nav).replace(",", "X").replace(".", ",").replace("X", ".")
        
        ytd = item.get("return_ytd", "0,00")
        w1 = item.get("return_1w", "0,00")
        m1 = item.get("return_1m", "0,00")
        
        # Simpel trend-indikator (Sammenligner 1 uge mod 1 måned)
        trend_icon = "↗️" if parse_pct(w1) > parse_pct(m1) else "↘️" if parse_pct(w1) < parse_pct(m1) else "➡️"
        
        # README række
        readme_content += f"| {item.get('name', 'Ukendt')[:35]} | {nav_display} | {ytd}% | {trend_icon} |\n"

        # HTML række til daily.html
        color = "green" if parse_pct(ytd) >= 0 else "red"
        rows_html += f"""
        <tr>
            <td><strong>{item.get('name', item.get('isin'))}</strong></td>
            <td style="font-family: monospace; text-align: right;">{nav_display}</td>
            <td style="color: {color}; text-align: right; font-weight: bold;">{ytd}%</td>
            <td style="text-align: center;">{trend_icon}</td>
            <td style="text-align: center;"><a href="{item.get('url', '#')}" target="_blank">PDF</a></td>
        </tr>
        """

    # Gem README.md
    README_FILE.write_text(readme_content, encoding="utf-8")
    
    # --- START HTML GENERERING ---
    html_template = f"""
    <!DOCTYPE html>
    <html lang="da">
    <head>
        <meta charset="utf-8">
        <title>TrendAgent Rapport</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; margin: 40px; background: #f4f7f6; }}
            .container {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; border-bottom: 1px solid #eee; text-align: left; }}
            th {{ background: #1a73e8; color: white; }}
            tr:hover {{ background: #f9f9f9; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>TrendAgent Dashboard</h1>
                <p>Opdateret: {timestamp}</p>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Investeringsfond</th>
                        <th style="text-align: right;">Kurs (NAV)</th>
                        <th style="text-align: right;">ÅTD Afkast</th>
                        <th style="text-align: center;">Trend</th>
                        <th style="text-align: center;">Link</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_template, encoding="utf-8")
    print(f"Succes: README.md og daily.html er opdateret kl. {timestamp}")

if __name__ == "__main__":
    build_report()
