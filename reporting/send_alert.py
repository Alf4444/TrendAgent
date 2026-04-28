"""
send_alert.py — Trail Stop e-mail notifikation
===============================================
Læser high_water_marks.json og latest.json og sender en e-mail
hvis nogen aktive fonde har udløst Trail Stop.

Kaldes fra GitHub Actions efter rapport-bygningen:
    python reporting/send_alert.py --trail-pct 3.0

Miljøvariabler (GitHub Secrets):
    MAIL_USERNAME    fx. ditbrugernavn@gmail.com
    MAIL_PASSWORD    Gmail App Password (ikke dit login-kodeord)
    MAIL_RECIPIENTS  Kommasepareret liste: a@b.com,c@d.com

Testtilstand:
    python reporting/send_alert.py --trail-pct 0.1
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

ROOT          = Path(__file__).resolve().parents[1]
HWM_FILE      = ROOT / "data/high_water_marks.json"
LATEST_FILE   = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


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


def find_trail_stop_alerts(portfolio, latest_map, hwm_data, trail_pct):
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

        hwm_entry  = hwm_data.get(isin, {})
        hwm        = hwm_entry.get("hwm", buy_price)
        hwm_date   = hwm_entry.get("hwm_date", "?")

        fall_pct = ((curr_price / hwm) - 1) * 100 if hwm > 0 else 0.0

        if fall_pct <= -trail_pct:
            total_ret = round(((curr_price / buy_price) - 1) * 100, 2) if buy_price else 0
            alerts.append({
                "name":      p_info.get("name", isin),
                "isin":      isin,
                "hwm":       round(hwm, 2),
                "hwm_date":  hwm_date,
                "curr":      round(curr_price, 2),
                "fall_pct":  round(fall_pct, 2),
                "buy_price": round(buy_price, 2),
                "total_ret": total_ret,
                "currency":  fund.get("currency", ""),
            })

    return alerts


def build_html_email(alerts, trail_pct, report_type):
    """Bygger en pæn HTML-mail med alle trail stop advarsler."""
    now = datetime.now().strftime("%d-%m-%Y %H:%M")
    rows_html = ""
    for a in alerts:
        total_color = "#28a745" if a["total_ret"] >= 0 else "#d93025"
        sign = "+" if a["total_ret"] >= 0 else ""
        rows_html += f"""
        <tr>
            <td style="padding:12px 10px; border-bottom:1px solid #f0f0f0; font-weight:bold;">
                {a['name']}
            </td>
            <td style="padding:12px 10px; border-bottom:1px solid #f0f0f0; color:#666; font-size:12px;">
                {a['isin']}
            </td>
            <td style="padding:12px 10px; border-bottom:1px solid #f0f0f0;">
                {a['hwm']} {a['currency']}<br>
                <small style="color:#999;">({a['hwm_date']})</small>
            </td>
            <td style="padding:12px 10px; border-bottom:1px solid #f0f0f0;">
                {a['curr']} {a['currency']}
            </td>
            <td style="padding:12px 10px; border-bottom:1px solid #f0f0f0; color:#d93025; font-weight:bold;">
                {a['fall_pct']}%
            </td>
            <td style="padding:12px 10px; border-bottom:1px solid #f0f0f0;
                       color:{total_color}; font-weight:bold;">
                {sign}{a['total_ret']}%
            </td>
        </tr>"""

    plural = "advarsel" if len(alerts) == 1 else "advarsler"
    test_banner = ""
    if trail_pct < 1.0:
        test_banner = """
        <div style="background:#fff3cd; border:1px solid #ffeeba; border-radius:8px;
                    padding:10px 15px; margin-bottom:20px; color:#856404; font-size:13px;">
            🧪 <strong>TESTKØRSEL</strong> — Tærsklen er sat til {:.1f}% for at verificere
            at e-mail notifikationen virker korrekt. Skift til 3.0% i produktionen.
        </div>""".format(trail_pct)

    html = f"""<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             background:#f4f7f9; margin:0; padding:20px;">
  <div style="max-width:800px; margin:auto; background:white; border-radius:12px;
              box-shadow:0 4px 12px rgba(0,0,0,0.08); overflow:hidden;">

    <!-- HEADER -->
    <div style="background:#d93025; padding:25px 30px; color:white;">
      <h1 style="margin:0; font-size:22px;">⚠️ Trail Stop Advarsel</h1>
      <p style="margin:5px 0 0 0; opacity:0.9; font-size:14px;">
        {report_type} · {now} · Tærskel: {trail_pct}%
      </p>
    </div>

    <div style="padding:25px 30px;">
      {test_banner}

      <p style="color:#333; font-size:15px;">
        <strong>{len(alerts)} fond{'e' if len(alerts) > 1 else ''}</strong> har udløst
        en Trail Stop {plural} og er faldet mere end <strong>{trail_pct}%</strong>
        fra sit High Water Mark:
      </p>

      <table style="width:100%; border-collapse:collapse; font-size:14px; margin-top:15px;">
        <thead>
          <tr style="background:#f8f9fa;">
            <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                       border-bottom:2px solid #eee;">Fond</th>
            <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                       border-bottom:2px solid #eee;">ISIN</th>
            <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                       border-bottom:2px solid #eee;">HWM (dato)</th>
            <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                       border-bottom:2px solid #eee;">Aktuel kurs</th>
            <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                       border-bottom:2px solid #eee;">Fald fra top</th>
            <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                       border-bottom:2px solid #eee;">Total afkast</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>

      <div style="margin-top:25px; padding:15px; background:#fce8e6; border-radius:8px;
                  border-left:4px solid #d93025;">
        <strong style="color:#c5221f;">Hvad gør du nu?</strong>
        <p style="margin:8px 0 0 0; color:#555; font-size:13px;">
          Gennemgå de markerede fonde i din månedlige Deep Dive rapport.
          Overvej om momentumet stadig er intakt, eller om det er tid til at
          rotere til en stærkere fond i universet.
        </p>
      </div>
    </div>

    <div style="padding:15px 30px; background:#f8f9fa; border-top:1px solid #eee;
                font-size:12px; color:#999;">
      Sendt automatisk fra TrendAgent · GitHub Actions
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
        "--report-type", type=str, default="Weekly rapport",
        help="Hvilken rapport der kalder scriptet (vises i mailen)"
    )
    args = parser.parse_args()

    # Hent credentials fra miljøvariabler (GitHub Secrets)
    username   = os.environ.get("MAIL_USERNAME", "").strip()
    password   = os.environ.get("MAIL_PASSWORD", "").strip()
    recipients_raw = os.environ.get("MAIL_RECIPIENTS", "").strip()

    if not username or not password or not recipients_raw:
        print("⚠️  MAIL_USERNAME, MAIL_PASSWORD eller MAIL_RECIPIENTS mangler — springer mail over.")
        sys.exit(0)

    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    # Indlæs data
    portfolio  = load_json(PORTFOLIO_FILE)
    latest_list = load_json(LATEST_FILE)
    hwm_data   = load_json(HWM_FILE) if HWM_FILE.exists() else {}

    latest_map = {item["isin"]: item for item in latest_list}

    # Find alerts
    alerts = find_trail_stop_alerts(
        portfolio, latest_map, hwm_data, args.trail_pct
    )

    if not alerts:
        print(f"✅ Ingen Trail Stop alerts ved {args.trail_pct}% tærskel — ingen mail sendt.")
        sys.exit(0)

    print(f"🔔 {len(alerts)} Trail Stop alert(s) fundet — sender mail...")

    subject   = f"⚠️ Trail Stop: {len(alerts)} fond{'e' if len(alerts) > 1 else ''} udløst ({args.trail_pct}%)"
    html_body = build_html_email(alerts, args.trail_pct, args.report_type)

    send_email(subject, html_body, username, password, recipients)


if __name__ == "__main__":
    main()
