import json
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
REPORT_FILE = ROOT / "build/daily.html"
README_FILE = ROOT / "README.md"

def get_ma(prices, window):
    clean_prices = [p for p in prices if p is not None]
    if len(clean_prices) < window: return None
    # Da vi kun har få datapunkter i starten, simulerer vi MA ved at bruge det vi har
    return sum(clean_prices[-window:]) / len(clean_prices[-window:])

def format_dk(value, is_pct=False):
    if value is None: return "–"
    res = "{:,.2f}".format(value).replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{res}%" if is_pct else res

def build_report():
    if not DATA_FILE.exists(): return
        
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        latest_data = json.load(f)
    with open(HISTORY_FILE, "r") as f:
        history = json.load(f)
    with open(PORTFOLIO_FILE, "r") as f:
        portfolio = json.load(f)

    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')

    # --- TRIN A: AUTOMATISK OPRYDNING OG BACKFILL ---
    cleaned_history = {}
    start_date = "2026-02-18"
    
    for isin, dates in history.items():
        # Behold kun rigtige data fra 18/02 ELLER meget gamle data (backfill fra 1år siden)
        # Vi fjerner alt mellem f.eks. 2024 og 2026-02-17 som var test
        valid_dates = {}
        for d, v in dates.items():
            if d >= start_date or d < "2025-06-01": # Beholder backfill (1år+) og ny data
                valid_dates[d] = v
        cleaned_history[isin] = valid_dates

    processed_list = []
    for item in latest_data:
        isin = item.get('isin')
        nav = item.get('nav')
        if nav is None: continue
        
        # Hent priser og beregn indikatorer
        price_dict = cleaned_history.get(isin, {})
        # Tilføj dagens pris til beregningen
        price_dict[datetime.now().strftime('%Y-%m-%d')] = nav
        price_history = [v for k, v in sorted(price_dict.items())]
        
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        ma200 = get_ma(price_history, 200)
        
        prev_nav = price_history[-2] if len(price_history) > 1 else nav
        day_chg = ((nav - prev_nav) / prev_nav * 100) if prev_nav else 0
        dist_ma200 = ((nav - (ma200 or nav)) / (ma200 or nav) * 100)
        
        # Signal logik
        signal, has_signal = "–", 0
        if ma200:
            curr_bull = nav > ma200
            prev_ma200 = get_ma(price_history[:-1], 200) or ma200
            prev_bull = prev_nav > prev_ma200
            if curr_bull and not prev_bull: signal, has_signal = "🚀 KØB", 1
            elif not curr_bull and prev_bull: signal, has_signal = "⚠️ SALG", 1

        is_active = portfolio.get(isin, {}).get('active', False)
        
        processed_list.append({
            'isin': isin, 'name': item.get('name'), 'nav': nav,
            'day_chg': day_chg, 'dist_ma200': dist_ma200,
            'ma20': ma20, 'ma50': ma50, 'ma200': ma200,
            'signal': signal, 'has_signal': has_signal,
            'is_active': is_active, 'history': price_history
        })

    # SORTERING: Aktive først -> Signaler -> Største bevægelser
    sorted_data = sorted(processed_list, key=lambda x: (not x['is_active'], not x['has_signal'], -abs(x['day_chg'])))

    # HTML & README GEN
    rows_html = ""
    readme_content = f"# 📈 TrendAgent Fokus\nOpdateret: {timestamp}\n\n| Stat | Signal | Fond | 1D % | Egen % | Afst. | Trend |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"

    for d in sorted_data:
        p_data = portfolio.get(d['isin'], {})
        buy_price = p_data.get('buy_price')
        p_ret_html = "–"
        if d['is_active'] and buy_price:
            p_ret = ((d['nav'] - buy_price) / buy_price * 100)
            p_color = "#1a73e8" if p_ret > 10 else ("#28a745" if p_ret > 0 else "#d93025")
            p_ret_html = f"<span style='color:{p_color}; font-weight:bold;'>{p_ret:+.1f}%</span>"

        t_state, t_color = ("BULL", "#28a745") if d['nav'] > (d['ma200'] or 0) else ("BEAR", "#d93025")
        ath = max(d['history']) if d['history'] else d['nav']
        dd = ((d['nav'] - ath) / ath * 100) if ath > 0 else 0

        row_style = "class='active-row'" if d['is_active'] else ("style='background:#e3f2fd;'" if d['has_signal'] else "")
        rows_html += f"""
        <tr {row_style}>
            <td>{'⭐' if d['is_active'] else '🔍'}</td>
            <td style="font-weight:bold; color:{'#1a73e8' if 'KØB' in d['signal'] else '#d93025'}">{d['signal']}</td>
            <td>{d['name'][:35]}</td>
            <td style="color:{'#28a745' if d['day_chg'] > 0 else '#d93025'}">{d['day_chg']:+.2f}%</td>
            <td>{p_ret_html}</td>
            <td style="font-weight:bold;">{d['dist_ma200']:+.1f}%</td>
            <td style="color:{t_color}; font-weight:bold;">{t_state}</td>
            <td style="color:#d93025">{dd:.1f}%</td>
        </tr>
        """
        if d['is_active'] or d['has_signal'] or abs(d['day_chg']) > 1.5:
            readme_content += f"| {'⭐' if d['is_active'] else '🔍'} | {d['signal']} | {d['name'][:18]} | {d['day_chg']:+.2f}% | {p_ret_html if d['is_active'] else '–'} | {d['dist_ma200']:+.1f}% | {t_state} |\n"

    REPORT_FILE.write_text(f"<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{font-family:sans-serif;background:#f4f7f9;margin:10px;}}table{{width:100%;border-collapse:collapse;background:white;font-size:12px;}}th,td{{padding:10px;border:1px solid #eee;text-align:left;}}th{{background:#1a73e8;color:white;position:sticky;top:0;}}.active-row{{background:#fff8e1;font-weight:bold;border-left:5px solid #ffca28;}}</style></head><body><h2>🚀 TrendAgent Fokus</h2><p>Opdateret: {timestamp}</p><table><thead><tr><th></th><th>Signal</th><th>Fond</th><th>1D %</th><th>Egen %</th><th>Afst.</th><th>Trend</th><th>Drawdown</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>", encoding="utf-8")
    README_FILE.write_text(readme_content, encoding="utf-8")
    
    # Gem den rensede historik tilbage
    with open(HISTORY_FILE, "w") as f:
        json.dump(cleaned_history, f)

if __name__ == "__main__":
    build_report()
