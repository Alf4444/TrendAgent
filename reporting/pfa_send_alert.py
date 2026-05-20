"""
send_alert.py — Trail Stop e-mail notifikation
===============================================
Læser pfa_hwm.json og pfa_latest.json og sender en e-mail
hvis nogen aktive fonde har udløst Trail Stop.

Kaldes fra GitHub Actions efter rapport-bygningen:
    python reporting/pfa_send_alert.py --trail-pct 3.0

Miljøvariabler (GitHub Secrets):
    MAIL_USERNAME    fx. ditbrugernavn@gmail.com
    MAIL_PASSWORD    Gmail App Password (ikke dit login-kodeord)
    MAIL_RECIPIENTS  Kommasepareret liste: a@b.com,c@d.com

Testtilstand:
    python reporting/pfa_send_alert.py --trail-pct 0.1
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT            = Path(__file__).resolve().parents[1]
HWM_FILE        = ROOT / "data/pfa_hwm.json"
LATEST_FILE     = ROOT / "data/pfa_latest.json"
PORTFOLIO_FILE  = ROOT / "config/pfa_portfolio.json"
RANK_HIST_FILE  = ROOT / "data/pfa_rank_history.json"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

PFA_FUND_URL = "https://pfapension.os.fundconnect.com/solutions/default/fundinfo-overview?language=en-GB&currency=DKK&isin={isin}"


def fund_link(isin, name):
    """Returnerer HTML-link til PFA fondsfaktaark."""
    url = PFA_FUND_URL.format(isin=isin)
    return f'<a href="{url}" style="color:#1a73e8; text-decoration:none;">{name} →</a>'


def load_rank_history():
    """Indlæser rank-historik. Format: {isin: {dato: rank}}"""
    if not RANK_HIST_FILE.exists():
        return {}
    try:
        with open(RANK_HIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_rank_history(data):
    RANK_HIST_FILE.parent.mkdir(exist_ok=True)
    with open(RANK_HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_ranks(latest_list):
    """Beregner rank for alle fonde baseret på 1M afkast. Rank 1 = bedst."""
    sorted_list = sorted(latest_list, key=lambda x: x.get('return_1m') or -999, reverse=True)
    return {item['isin']: i + 1 for i, item in enumerate(sorted_list)}


def get_rank_arrow(isin, today_rank, rank_history):
    """
    Sammenligner dagens rank med gårsdagens.
    Returnerer (prev_rank, arrow) hvor arrow er ↑, ↓ eller →
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    hist = rank_history.get(isin, {})

    # Find seneste tidligere dato
    prev_dates = sorted([d for d in hist.keys() if d < today_str], reverse=True)
    if not prev_dates:
        return None, '→'

    prev_rank = hist[prev_dates[0]]
    if today_rank < prev_rank:
        arrow = '↑'
    elif today_rank > prev_rank:
        arrow = '↓'
    else:
        arrow = '→'

    return prev_rank, arrow


def update_rank_history(rank_map, rank_history):
    """Gemmer dagens rank i historikken."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    for isin, rank in rank_map.items():
        if isin not in rank_history:
            rank_history[isin] = {}
        rank_history[isin][today_str] = rank
    # Behold kun seneste 7 dage
    cutoff = sorted(rank_history.get(list(rank_history.keys())[0], {}).keys())[-7] \
        if rank_history else None
    if cutoff:
        for isin in rank_history:
            rank_history[isin] = {
                d: r for d, r in rank_history[isin].items() if d >= cutoff
            }
    return rank_history


def get_rotation_alternatives(portfolio, latest_list, rank_map, rank_history, n=3):
    """
    Finder top-N ikke-ejede fonde som rotationsalternativer.
    Sorteret primært på return_1m, sekundært på return_3m.
    Inkluderer rank og rank-pil.
    """
    owned_isins = {isin for isin, p in portfolio.items() if p.get('active', False)}

    candidates = [
        item for item in latest_list
        if item['isin'] not in owned_isins
        and item.get('return_1m') is not None
    ]

    candidates.sort(
        key=lambda x: (x.get('return_1m') or -999, x.get('return_3m') or -999),
        reverse=True
    )

    result = []
    for item in candidates[:n]:
        isin      = item['isin']
        rank      = rank_map.get(isin)
        _, arrow  = get_rank_arrow(isin, rank, rank_history)
        result.append({
            'isin':      isin,
            'name':      item['name'],
            'return_1m': item.get('return_1m'),
            'return_3m': item.get('return_3m'),
            'rank':      rank,
            'arrow':     arrow,
            'total':     len(latest_list),
        })

    return result


def get_other_positions(alert_isin, portfolio, latest_list, rank_map, rank_history):
    """
    Returnerer øvrige aktive positioner (ikke den der har udløst alarm)
    med rank, pil og afkast.
    """
    latest_map = {item['isin']: item for item in latest_list}
    result = []
    for isin, p_info in portfolio.items():
        if not p_info.get('active', False) or isin == alert_isin:
            continue
        item     = latest_map.get(isin, {})
        rank     = rank_map.get(isin)
        _, arrow = get_rank_arrow(isin, rank, rank_history)
        result.append({
            'isin':      isin,
            'name':      p_info.get('name', isin),
            'return_1m': item.get('return_1m'),
            'return_3m': item.get('return_3m'),
            'rank':      rank,
            'arrow':     arrow,
            'total':     len(latest_list),
        })
    return result


def get_vurdering(rank, arrow, return_3m, total):
    """
    Returnerer (emoji, titel, tekst) baseret på rank-trend og 3M afkast.
    """
    rank_falling = arrow == '↓'
    m3_weak      = (return_3m or 0) < 5

    if rank_falling and m3_weak:
        return '🔴', 'Rotation bør overvejes', \
               'Rank falder og 3M afkast svækkes. Andre fonde løber hurtigere.'
    elif rank_falling and not m3_weak:
        return '👀', 'Hold øje — farten aftager', \
               'Rank falder men 3M afkast er stadig stærkt. Kan være en normal korrektion.'
    elif not rank_falling and m3_weak:
        return '👀', 'Hold øje — markedet svækkes', \
               'Rank er stabilt men 3M afkast er svagt. Følg udviklingen tæt.'
    else:
        return '✅', 'Normal korrektion — hold', \
               'Rank er stabilt og 3M afkast er stærkt. Sandsynligvis et midlertidigt tilbagefald.'


# ==========================================
# HJÆLPEFUNKTIONER
# ==========================================

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Kunne ikke læse {path}: {e}")
        sys.exit(1)


def days_since_hwm(hwm_date_str):
    """Beregner antal dage siden High Water Mark blev sat."""
    try:
        hwm_date = datetime.strptime(hwm_date_str, '%Y-%m-%d')
        return (datetime.now() - hwm_date).days
    except Exception:
        return None


def find_trail_stop_alerts(portfolio, latest_list, latest_map, hwm_data, trail_pct,
                           rank_map, rank_history):
    """
    Gennemgår aktive fonde og returnerer en liste af alerts
    for fonde der er faldet mere end trail_pct % fra HWM.
    """
    alerts = []
    for isin, p_info in portfolio.items():
        if not p_info.get("active", False):
            continue

        fund = latest_map.get(isin)
        if not fund:
            continue

        curr_price = fund.get("nav") or 0
        buy_price  = p_info.get("buy_price") or 0

        if not curr_price or not buy_price:
            continue

        hwm_entry = hwm_data.get(isin, {})
        hwm       = hwm_entry.get("hwm", buy_price)
        hwm_date  = hwm_entry.get("hwm_date", "?")

        fall_pct = ((curr_price / hwm) - 1) * 100 if hwm > 0 else 0.0

        if fall_pct <= -trail_pct:
            total_ret        = round(((curr_price / buy_price) - 1) * 100, 2) if buy_price else 0
            rank             = rank_map.get(isin)
            prev_rank, arrow = get_rank_arrow(isin, rank, rank_history)
            days_hwm         = days_since_hwm(hwm_date)
            return_1m        = fund.get("return_1m")
            return_3m        = fund.get("return_3m")
            total_funds      = len(latest_list)
            emoji, vurd_titel, vurd_tekst = get_vurdering(rank, arrow, return_3m, total_funds)

            alerts.append({
                "name":        p_info.get("name", isin),
                "isin":        isin,
                "hwm":         round(hwm, 2),
                "hwm_date":    hwm_date,
                "days_hwm":    days_hwm,
                "curr":        round(curr_price, 2),
                "buy_price":   round(buy_price, 2),
                "fall_pct":    round(fall_pct, 2),
                "total_ret":   total_ret,
                "return_1m":   return_1m,
                "return_3m":   return_3m,
                "rank":        rank,
                "prev_rank":   prev_rank,
                "arrow":       arrow,
                "total_funds": total_funds,
                "currency":    fund.get("currency", ""),
                "emoji":       emoji,
                "vurd_titel":  vurd_titel,
                "vurd_tekst":  vurd_tekst,
            })

    return alerts


def build_html_email(alerts, trail_pct, report_type, portfolio, latest_list,
                     rank_map, rank_history):
    """Bygger HTML-mail med trail stop advarsler, vurdering og rotationsforslag."""
    now         = datetime.now().strftime("%d-%m-%Y %H:%M")
    total_funds = alerts[0]['total_funds'] if alerts else len(latest_list)

    # --- TEST BANNER ---
    test_banner = ""
    if trail_pct < 1.0:
        test_banner = f"""
        <div style="background:#fff3cd; border:1px solid #ffeeba; border-radius:8px;
                    padding:10px 15px; margin-bottom:20px; color:#856404; font-size:13px;">
            🧪 <strong>TESTKØRSEL</strong> — Tærsklen er sat til {trail_pct:.1f}%.
        </div>"""

    def fmt_ret(val, suffix=""):
        if val is None: return "N/A"
        sign = "+" if val >= 0 else ""
        color = "#28a745" if val >= 0 else "#d93025"
        return f'<span style="color:{color}; font-weight:700;">{sign}{val:.2f}%{suffix}</span>'

    def rank_badge(rank, arrow, total):
        if rank is None: return "—"
        arrow_color = {"↑": "#28a745", "↓": "#d93025", "→": "#888"}.get(arrow, "#888")
        return (f'#{rank} / {total} '
                f'<span style="color:{arrow_color}; font-weight:700;">{arrow}</span>')

    # --- FOND-KORT PER ALERT ---
    alerts_html = ""
    for a in alerts:
        fund_url  = f"https://pfapension.os.fundconnect.com/solutions/default/fundinfo-overview?language=en-GB&currency=DKK&isin={a['isin']}"
        days_str  = f"{a['days_hwm']} dage siden" if a.get('days_hwm') is not None else "?"
        vurd_color = {"✅": "#28a745", "👀": "#f59c00", "🔴": "#d93025"}.get(a.get("emoji",""), "#555")

        # Øvrige positioner
        others       = get_other_positions(a["isin"], portfolio, latest_list, rank_map, rank_history)
        others_rows  = ""
        for o in others:
            o_url = f"https://pfapension.os.fundconnect.com/solutions/default/fundinfo-overview?language=en-GB&currency=DKK&isin={o['isin']}"
            others_rows += f"""
              <div style="padding:5px 0; border-bottom:1px solid #f0f0f0; font-size:12px;">
                · <a href="{o_url}" style="color:#1a73e8; text-decoration:none; font-weight:600;">{o['name']} →</a>
                &nbsp; {rank_badge(o['rank'], o['arrow'], o['total'])}
                &nbsp; 1M: {fmt_ret(o['return_1m'])}
                &nbsp; 3M: {fmt_ret(o['return_3m'])}
              </div>"""

        # Top 3 alternativer
        alternatives  = get_rotation_alternatives(portfolio, latest_list, rank_map, rank_history)
        alt_rows      = ""
        for alt in alternatives:
            alt_url = f"https://pfapension.os.fundconnect.com/solutions/default/fundinfo-overview?language=en-GB&currency=DKK&isin={alt['isin']}"
            alt_rows += f"""
              <div style="padding:5px 0; border-bottom:1px solid #f0f0f0; font-size:12px;">
                · <a href="{alt_url}" style="color:#1a73e8; text-decoration:none; font-weight:600;">{alt['name']} →</a>
                &nbsp; {rank_badge(alt['rank'], alt['arrow'], alt['total'])}
                &nbsp; 1M: {fmt_ret(alt['return_1m'])}
                &nbsp; 3M: {fmt_ret(alt['return_3m'])}
              </div>"""

        alerts_html += f"""
        <div style="background:white; border-radius:10px; margin-bottom:20px;
                    box-shadow:0 2px 8px rgba(0,0,0,0.08); overflow:hidden;
                    border-left:4px solid {vurd_color};">

          <!-- FOND TITEL -->
          <div style="padding:16px 20px; border-bottom:1px solid #f0f0f0;">
            <div style="font-size:16px; font-weight:700;">
              <a href="{fund_url}" style="color:#1a1a2e; text-decoration:none;">
                {a['name']} →
              </a>
              <span style="color:#d93025; font-size:14px; font-weight:700; margin-left:12px;">
                Trail Stop udløst ({a['fall_pct']:+.2f}% fra top)
              </span>
            </div>
          </div>

          <!-- NØGLETAL -->
          <div style="padding:14px 20px; border-bottom:1px solid #f0f0f0;">
            <table style="font-size:13px; border-collapse:collapse; width:100%;">
              <tr>
                <td style="padding:4px 16px 4px 0; color:#666; white-space:nowrap;">Rank i dag</td>
                <td style="padding:4px 0; font-weight:600;">{rank_badge(a['rank'], a['arrow'], a['total_funds'])}</td>
              </tr>
              <tr>
                <td style="padding:4px 16px 4px 0; color:#666;">1M afkast</td>
                <td style="padding:4px 0;">{fmt_ret(a['return_1m'])}</td>
              </tr>
              <tr>
                <td style="padding:4px 16px 4px 0; color:#666;">3M afkast</td>
                <td style="padding:4px 0;">{fmt_ret(a['return_3m'])}</td>
              </tr>
              <tr>
                <td style="padding:4px 16px 4px 0; color:#666;">Afkast fra køb</td>
                <td style="padding:4px 0;">{fmt_ret(a['total_ret'])}</td>
              </tr>
              <tr>
                <td style="padding:4px 16px 4px 0; color:#666;">HWM</td>
                <td style="padding:4px 0; color:#555;">{a['hwm']} {a['currency']} ({days_str})</td>
              </tr>
            </table>
          </div>

          <!-- VURDERING -->
          <div style="padding:12px 20px; border-bottom:1px solid #f0f0f0;
                      background:#fafafa;">
            <span style="font-weight:700; color:{vurd_color};">
              {a.get('emoji','')} {a.get('vurd_titel','')}
            </span>
            <div style="font-size:12px; color:#555; margin-top:4px;">
              {a.get('vurd_tekst','')}
            </div>
          </div>

          <!-- ØVRIGE POSITIONER -->
          {"" if not others_rows else f'''
          <div style="padding:12px 20px; border-bottom:1px solid #f0f0f0;">
            <div style="font-size:11px; font-weight:700; color:#888; margin-bottom:6px;
                        text-transform:uppercase; letter-spacing:0.5px;">
              Dine øvrige positioner
            </div>
            {others_rows}
          </div>'''}

          <!-- TOP 3 ALTERNATIVER -->
          {"" if not alt_rows else f'''
          <div style="padding:12px 20px;">
            <div style="font-size:11px; font-weight:700; color:#888; margin-bottom:6px;
                        text-transform:uppercase; letter-spacing:0.5px;">
              Top 3 alternativer du ikke ejer
            </div>
            {alt_rows}
          </div>'''}

        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             background:#f4f7f9; margin:0; padding:20px;">
  <div style="max-width:700px; margin:auto;">

    <!-- HEADER -->
    <div style="background:#d93025; padding:20px 24px; color:white;
                border-radius:10px 10px 0 0;">
      <h1 style="margin:0; font-size:20px;">⚠️ Trail Stop Advarsel</h1>
      <p style="margin:4px 0 0; opacity:0.9; font-size:13px;">
        {report_type} · {now} · Tærskel: {trail_pct}%
      </p>
    </div>

    <div style="background:white; padding:20px 24px; border:1px solid #eee;
                border-radius:0 0 10px 10px; margin-bottom:16px;">
      {test_banner}
      <p style="color:#333; font-size:14px; margin:0 0 20px;">
        <strong>{len(alerts)} fond{"e" if len(alerts) > 1 else ""}</strong>
        har udløst Trail Stop og er faldet mere end <strong>{trail_pct}%</strong>
        fra sit High Water Mark:
      </p>
      {alerts_html}
    </div>

    <!-- FOOTER -->
    <div style="font-size:11px; color:#aaa; text-align:center; padding:8px 0;">
      TrendAgent · GitHub Actions · {now}
    </div>
  </div>
</body>
</html>"""
    return html


def send_email(subject, html_body, username, password, recipients):
    """Sender HTML-mail via Gmail SMTP med TLS."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = username
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(username, password)
            server.sendmail(username, recipients, msg.as_string())
        print(f"✅ Mail sendt til: {', '.join(recipients)}")
    except smtplib.SMTPAuthenticationError:
        print("❌ SMTP login fejlede — tjek MAIL_USERNAME og MAIL_PASSWORD (brug App Password).")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Mail-fejl: {e}")
        sys.exit(1)


# ==========================================
# MAIN
# ==========================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trail-pct", type=float, default=3.0,
        help="Trail Stop tærskel i %% (brug 0.1 til test, 3.0 i produktion)"
    )
    parser.add_argument(
        "--report-type", type=str, default="Daily Radar",
        help="Hvilken rapport der kalder scriptet (vises i mailen)"
    )
    args = parser.parse_args()

    username       = os.environ.get("MAIL_USERNAME", "").strip()
    password       = os.environ.get("MAIL_PASSWORD", "").strip()
    recipients_raw = os.environ.get("MAIL_RECIPIENTS", "").strip()

    if not username or not password or not recipients_raw:
        print("⚠️  MAIL_USERNAME, MAIL_PASSWORD eller MAIL_RECIPIENTS mangler — springer mail over.")
        sys.exit(0)

    recipients  = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    portfolio   = load_json(PORTFOLIO_FILE)
    latest_list = load_json(LATEST_FILE)
    hwm_data    = load_json(HWM_FILE) if HWM_FILE.exists() else {}
    latest_map  = {item["isin"]: item for item in latest_list}

    # Rank-system
    rank_map     = build_ranks(latest_list)
    rank_history = load_rank_history()
    rank_history = update_rank_history(rank_map, rank_history)
    save_rank_history(rank_history)

    alerts = find_trail_stop_alerts(
        portfolio, latest_list, latest_map, hwm_data, args.trail_pct,
        rank_map, rank_history
    )

    if not alerts:
        print(f"✅ Ingen Trail Stop alerts ved {args.trail_pct}% tærskel — ingen mail sendt.")
        sys.exit(0)

    print(f"🔔 {len(alerts)} Trail Stop alert(s) fundet — sender mail...")
    subject   = f"⚠️ Trail Stop: {len(alerts)} fond{'e' if len(alerts) > 1 else ''} udløst ({args.trail_pct}%)"
    html_body = build_html_email(
        alerts, args.trail_pct, args.report_type,
        portfolio, latest_list, rank_map, rank_history
    )
    send_email(subject, html_body, username, password, recipients)


if __name__ == "__main__":
    main()
