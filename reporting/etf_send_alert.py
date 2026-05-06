"""
etf_send_alert.py — Mail-alarm for ETF Spejder
================================================
Sendes Man/Ons/Fre hvis der er nye Hurtige Heste
eller Trail Stop-advarsler i ETF-porteføljen.

Køres af .github/workflows/etf_alert.yml
"""

import json
import os
import sys
import smtplib
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT           = Path(__file__).resolve().parents[1]
HITS_FILE      = ROOT / "data/etf_spejder_hits.json"
HWM_FILE       = ROOT / "data/etf_hwm.json"
PORTFOLIO_FILE = ROOT / "config/etf_portfolio.json"
LATEST_FILE    = ROOT / "data/etf_latest.json"

# Alarm-konfiguration
# Juster disse vaerdier over tid baseret paa erfaring
SPEJDER_MIN_WEEKS = 1   # Antal uger en fond skal vaere paa listen inden alarm
                         # Start: 1 uge. Oeges til 2-3 hvis for mange alarmer.


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if not k.startswith('_')}
            return data
    except Exception:
        return default


def get_weakest_position(portfolio, latest_map, hwm_data):
    """
    Finder den svaageste aktive position baseret paa rank og momentum.
    Bruges til rotationsforslag i alarm-mailen.
    """
    active = {isin: p for isin, p in portfolio.items() if p.get('active', False)}
    if not active:
        return None

    candidates = []
    for isin, p_info in active.items():
        if isin not in latest_map:
            continue
        item    = latest_map[isin]
        return_1m = item.get('return_1m') or 0
        return_1y = item.get('return_1y') or 0
        candidates.append({
            "isin":      isin,
            "name":      p_info.get('name', isin),
            "ticker":    p_info.get('ticker', ''),
            "return_1m": return_1m,
            "return_1y": return_1y,
            "buy_price": p_info.get('buy_price', 0),
            "curr_price": item.get('nav', 0),
        })

    if not candidates:
        return None

    # Svaageste = lavest 1M afkast
    return sorted(candidates, key=lambda x: x['return_1m'])[0]


def build_email_html(nye_hits, trail_alerts, portfolio, latest_map, hwm_data):
    """Bygger HTML-indhold til alarm-mailen."""
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    weakest = get_weakest_position(portfolio, latest_map, hwm_data)

    rows_nye = ""
    for h in nye_hits:
        rsi_warn = f" ⚠️ RSI {h['rsi']:.0f}" if h.get('rsi') and h['rsi'] >= 70 else ""
        golden   = " 🚀 GOLDEN CROSS" if h.get('cross') == "🚀 GOLDEN" else ""
        rows_nye += f"""
        <tr>
          <td style="padding:8px; border-bottom:1px solid #eee;">
            <strong>{h['name']}</strong><br>
            <small style="color:#888;">{h.get('ticker','')}</small>
          </td>
          <td style="padding:8px; border-bottom:1px solid #eee; color:#e53935; font-weight:700;">
            +{h['momentum']:.1f}% over MA
          </td>
          <td style="padding:8px; border-bottom:1px solid #eee; color:#1e8e3e; font-weight:700;">
            {f"+{h['return_1y']:.1f}%" if h.get('return_1y') else '–'}
          </td>
          <td style="padding:8px; border-bottom:1px solid #eee;">
            {f"{h['rsi']:.0f}" if isinstance(h.get('rsi'), float) else "–"}{rsi_warn}{golden}
          </td>
          <td style="padding:8px; border-bottom:1px solid #eee; color:#888; font-size:11px;">
            TER: {h.get('ter', '–')}%
          </td>
        </tr>"""

    # Rotationsforslag
    rotation_html = ""
    if weakest and nye_hits:
        best_new = nye_hits[0]
        rotation_html = f"""
        <div style="background:#fff8e1; border-left:4px solid #f59c00; padding:12px 16px; margin:16px 0; border-radius:4px;">
          <strong>🔄 Mulig rotation</strong><br>
          <span style="font-size:13px;">
            Overvej at sælge <strong>{weakest['name']}</strong>
            ({weakest['return_1m']:+.1f}% seneste måned)
            og købe <strong>{best_new['name']}</strong>
            (+{best_new['momentum']:.1f}% momentum, {f"+{best_new['return_1y']:.1f}% 1Y" if best_new.get('return_1y') else ''}).
          </span><br>
          <small style="color:#888;">
            Tjek altid Trail Stop-status og RSI inden du handler.
            En advarsel er ikke automatisk et købs-/salgssignal.
          </small>
        </div>"""

    # Trail Stop advarsler
    trail_html = ""
    if trail_alerts:
        trail_rows = ""
        for a in trail_alerts:
            trail_rows += f"""
            <tr>
              <td style="padding:8px;">{a.get('name', a.get('isin','?'))}</td>
              <td style="padding:8px; color:#d93025; font-weight:700;">{a['fall_pct']:+.1f}% fra top</td>
              <td style="padding:8px;">HWM: {a['hwm']} → Nu: {a['curr']}</td>
              <td style="padding:8px; color:#888;">Afkast fra køb: {a['total_ret']:+.1f}%</td>
            </tr>"""
        trail_html = f"""
        <h3 style="color:#d93025; margin-top:24px;">⚠️ Trail Stop Advarsler</h3>
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
          {trail_rows}
        </table>"""

    nye_section = f"""
        <h3 style="color:#e53935;">🚀 Nye Hurtige Heste denne uge ({len(nye_hits)})</h3>
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
          <tr style="background:#f5f5f5;">
            <th style="padding:8px; text-align:left;">Fond</th>
            <th style="padding:8px; text-align:left;">Momentum</th>
            <th style="padding:8px; text-align:left;">1Y afkast</th>
            <th style="padding:8px; text-align:left;">RSI</th>
            <th style="padding:8px; text-align:left;">TER</th>
          </tr>
          {rows_nye}
        </table>
        {rotation_html}
    """ if nye_hits else ""

    return f"""
    <html><body style="font-family: Arial, sans-serif; max-width:700px; margin:0 auto; color:#2c3e50;">
      <div style="background:linear-gradient(135deg,#1a1a2e,#16213e); color:white; padding:20px 24px; border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">📡 TrendAgent ETF Alarm</h2>
        <p style="margin:4px 0 0; color:#aaa; font-size:12px;">{now}</p>
      </div>
      <div style="background:white; padding:20px 24px; border:1px solid #eee; border-radius:0 0 8px 8px;">
        {nye_section}
        {trail_html}
        <hr style="margin:20px 0; border:none; border-top:1px solid #eee;">
        <p style="font-size:11px; color:#aaa;">
          Se fuld rapport: <a href="https://alf4444.github.io/TrendAgent/build/etf_weekly.html">ETF Weekly</a><br>
          Alarm-frekvens: Man/Ons/Fre · Min. uger på liste: {SPEJDER_MIN_WEEKS} uge(r)<br>
          Trail Stop: Variabelt 3-7% baseret på volatilitet
        </p>
      </div>
    </body></html>
    """


def send_mail(subject, html_body):
    """Sender mail via Gmail SMTP."""
    username   = os.environ.get("MAIL_USERNAME", "")
    password   = os.environ.get("MAIL_PASSWORD", "")
    recipients = os.environ.get("MAIL_RECIPIENTS", username)

    if not username or not password:
        print("❌ MAIL_USERNAME eller MAIL_PASSWORD mangler i environment")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = username
    msg['To']      = recipients
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(username, password)
            server.sendmail(username, recipients.split(','), msg.as_string())
        print(f"✅ Mail sendt til {recipients}")
        return True
    except Exception as e:
        print(f"❌ Mail fejlede: {e}")
        return False


def main():
    print("\n" + "="*50)
    print("📡 ETF SEND ALERT")
    print("="*50)

    hits      = load_json(HITS_FILE, {})
    portfolio = load_json(PORTFOLIO_FILE, {})
    latest    = load_json(LATEST_FILE, [])
    hwm_data  = load_json(HWM_FILE, {})

    latest_map = {item['isin']: item for item in latest} if isinstance(latest, list) else {}

    # Nye hurtige heste denne uge
    nye_hits = hits.get('hits_nye', []) if isinstance(hits, dict) else []

    # Trail Stop advarsler fra HWM-filen
    trail_alerts = []
    for isin, hwm_entry in hwm_data.items():
        if not isinstance(hwm_entry, dict):
            continue
        hwm_val = hwm_entry.get('hwm', 0)
        if not hwm_val:
            continue
        if isin not in latest_map:
            continue
        curr = latest_map[isin].get('nav', 0)
        if not curr:
            continue
        fall_pct = ((curr / hwm_val) - 1) * 100
        # Find Trail Stop tærskel (variabel baseret på volatilitet)
        volatility = latest_map[isin].get('volatility')
        if volatility and volatility >= 2.0:
            threshold = -7.0
        elif volatility and volatility >= 1.0:
            threshold = -5.0
        else:
            threshold = -3.0

        if fall_pct <= threshold:
            p_info = portfolio.get(isin, {})
            if p_info.get('active', False):
                buy_p = p_info.get('buy_price', 0)
                trail_alerts.append({
                    "isin":      isin,
                    "name":      p_info.get('name', isin),
                    "hwm":       round(hwm_val, 2),
                    "curr":      round(curr, 2),
                    "fall_pct":  round(fall_pct, 2),
                    "total_ret": round(((curr / buy_p) - 1) * 100, 2) if buy_p else 0,
                })

    if not nye_hits and not trail_alerts:
        print("✅ Ingen nye hits eller Trail Stop advarsler — ingen mail sendes")
        return

    # Byg og send mail
    antal = len(nye_hits)
    trail_antal = len(trail_alerts)

    subject_parts = []
    if nye_hits:
        subject_parts.append(f"{antal} ny{'e' if antal > 1 else ''} Hurtig Hest{'e' if antal > 1 else ''}")
    if trail_alerts:
        subject_parts.append(f"{trail_antal} Trail Stop")

    subject = f"📡 TrendAgent ETF — {' + '.join(subject_parts)}"

    html = build_email_html(nye_hits, trail_alerts, portfolio, latest_map, hwm_data)
    send_mail(subject, html)

    print(f"   Nye hits: {antal}")
    print(f"   Trail Stop: {trail_antal}")
    print("="*50)


if __name__ == "__main__":
    main()
