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

ROOT           = Path(__file__).resolve().parents[1]
HWM_FILE       = ROOT / "data/high_water_marks.json"
LATEST_FILE    = ROOT / "data/latest.json"
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


def get_rank(isin, latest_list):
    """
    Beregner fondens rang i hele universet baseret på 1M afkast.
    Rank 1 = bedste fond denne måned.
    """
    sorted_list = sorted(latest_list, key=lambda x: x.get('return_1m') or -999, reverse=True)
    for i, item in enumerate(sorted_list):
        if item['isin'] == isin:
            return i + 1
    return None


def days_since_hwm(hwm_date_str):
    """Beregner antal dage siden High Water Mark blev sat."""
    try:
        hwm_date = datetime.strptime(hwm_date_str, '%Y-%m-%d')
        return (datetime.now() - hwm_date).days
    except Exception:
        return None


def find_trail_stop_alerts(portfolio, latest_list, latest_map, hwm_data, trail_pct):
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
            total_ret = round(((curr_price / buy_price) - 1) * 100, 2) if buy_price else 0
            rank      = get_rank(isin, latest_list)
            days_hwm  = days_since_hwm(hwm_date)
            return_1m = fund.get("return_1m")

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
                "rank":        rank,
                "total_funds": len(latest_list),
                "currency":    fund.get("currency", ""),
            })

    return alerts


def build_html_email(alerts, trail_pct, report_type):
    """Bygger en pæn HTML-mail med alle trail stop advarsler."""
    now    = datetime.now().strftime("%d-%m-%Y %H:%M")
    plural = "advarsel" if len(alerts) == 1 else "advarsler"
    total_funds = alerts[0]['total_funds'] if alerts else 47

    # --- TEST BANNER ---
    test_banner = ""
    if trail_pct < 1.0:
        test_banner = f"""
        <div style="background:#fff3cd; border:1px solid #ffeeba; border-radius:8px;
                    padding:10px 15px; margin-bottom:20px; color:#856404; font-size:13px;">
            🧪 <strong>TESTKØRSEL</strong> — Tærsklen er sat til {trail_pct:.1f}% for at
            verificere at e-mail notifikationen virker korrekt. Skift til 3.0% i produktionen.
        </div>"""

    # --- FOND-RÆKKER ---
    rows_html = ""
    for a in alerts:
        total_color = "#28a745" if a["total_ret"] >= 0 else "#d93025"
        total_sign  = "+" if a["total_ret"] >= 0 else ""
        m1_color    = "#28a745" if (a["return_1m"] or 0) >= 0 else "#d93025"
        m1_sign     = "+" if (a["return_1m"] or 0) >= 0 else ""
        m1_val      = f"{m1_sign}{a['return_1m']}%" if a["return_1m"] is not None else "N/A"
        rank_str    = f"#{a['rank']} / {a['total_funds']}" if a["rank"] else "N/A"
        days_str    = f"{a['days_hwm']} dage siden" if a["days_hwm"] is not None else "?"

        rows_html += f"""
        <tr>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0; font-weight:bold;
                     font-size:13px;">{a['name']}</td>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0; color:#666;
                     font-size:11px;">{a['isin']}</td>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0; font-size:13px;">
              {a['buy_price']} {a['currency']}
          </td>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0; font-size:13px;">
              {a['hwm']} {a['currency']}<br>
              <small style="color:#999; font-size:11px;">{days_str}</small>
          </td>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0; font-size:13px;">
              {a['curr']} {a['currency']}
          </td>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0; color:#d93025;
                     font-weight:bold; font-size:13px;">{a['fall_pct']}%</td>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0;
                     color:{m1_color}; font-weight:bold; font-size:13px;">{m1_val}</td>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0; font-size:13px;">
              <span style="background:#2c3e50; color:white; padding:2px 7px;
                           border-radius:4px; font-size:11px; font-weight:bold;">
                  {rank_str}
              </span>
          </td>
          <td style="padding:14px 10px; border-bottom:1px solid #f0f0f0;
                     color:{total_color}; font-weight:bold; font-size:13px;">
              {total_sign}{a['total_ret']}%
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="da">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             background:#f4f7f9; margin:0; padding:20px;">
  <div style="max-width:900px; margin:auto; background:white; border-radius:12px;
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

      <p style="color:#333; font-size:15px; margin-bottom:20px;">
        <strong>{len(alerts)} fond{'e' if len(alerts) > 1 else ''}</strong> har udløst
        en Trail Stop {plural} og er faldet mere end <strong>{trail_pct}%</strong>
        fra sit High Water Mark:
      </p>

      <!-- FONDSTABEL -->
      <div style="overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
          <thead>
            <tr style="background:#f8f9fa;">
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">Fond</th>
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">ISIN</th>
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">Købspris</th>
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">HWM (siden)</th>
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">Aktuel kurs</th>
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">Fald fra top</th>
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">1M afkast</th>
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">Rank</th>
              <th style="padding:12px 10px; text-align:left; color:#666; font-weight:600;
                         border-bottom:2px solid #eee; white-space:nowrap;">Afkast fra køb</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </div>

      <!-- HVAD GØR DU NU -->
      <div style="margin-top:25px; padding:18px 20px; background:#fce8e6; border-radius:8px;
                  border-left:4px solid #d93025;">
        <strong style="color:#c5221f; font-size:14px;">⚡ Hvad gør du nu?</strong>
        <p style="margin:10px 0 0 0; color:#555; font-size:13px; line-height:1.7;">
          En Trail Stop advarsel betyder at fonden har mistet momentum fra sit toppunkt.
          Det er ikke automatisk et salgssignal — men et signal om at du skal handle aktivt.<br><br>
          <strong>Tjek følgende:</strong><br>
          1. Er <strong>1M afkast</strong> stadig positivt? Hvis ja, kan det være et midlertidigt tilbagefald.<br>
          2. Er <strong>Rank</strong> stadig i top 10 ud af {total_funds}? Hvis fonden er faldet ud af top 10, løber andre fonde hurtigere.<br>
          3. Er <strong>Fald fra top</strong> accelererende (mere end 5-7%)? Overvej at sælge og rotere til en stærkere fond.<br><br>
          Gennemgå fonden i din næste Deep Dive rapport for det fulde billede.
        </p>
      </div>

      <!-- DEFINITIONER -->
      <div style="margin-top:20px; padding:18px 20px; background:#f8f9fa; border-radius:8px;
                  border:1px solid #e8e8e8;">
        <strong style="color:#2c3e50; font-size:14px;">📖 Definitioner</strong>
        <table style="width:100%; margin-top:12px; font-size:12px; color:#555;
                      border-collapse:collapse;">
          <tr>
            <td style="padding:7px 12px 7px 0; font-weight:bold; color:#333;
                       white-space:nowrap; vertical-align:top; width:150px;">Købspris</td>
            <td style="padding:7px 0; line-height:1.6;">
              Den kurs du betalte da du købte fonden. Bruges som baseline for at
              beregne dit samlede afkast siden investering.
            </td>
          </tr>
          <tr style="border-top:1px solid #eee;">
            <td style="padding:7px 12px 7px 0; font-weight:bold; color:#333;
                       white-space:nowrap; vertical-align:top;">HWM</td>
            <td style="padding:7px 0; line-height:1.6;">
              High Water Mark — den højeste kurs fonden har haft siden du købte den.
              Opdateres automatisk hver gang fonden sætter ny top. Det er
              udgangspunktet for Trail Stop beregningen.
            </td>
          </tr>
          <tr style="border-top:1px solid #eee;">
            <td style="padding:7px 12px 7px 0; font-weight:bold; color:#333;
                       white-space:nowrap; vertical-align:top;">Dage siden HWM</td>
            <td style="padding:7px 0; line-height:1.6;">
              Antal dage siden fonden sidst satte sit High Water Mark. En fond der
              toppede for 2 dage siden er anderledes end en der toppede for 6 uger
              siden — sidstnævnte indikerer vedvarende tab af momentum og øger
              sandsynligheden for at det er tid til at rotere.
            </td>
          </tr>
          <tr style="border-top:1px solid #eee;">
            <td style="padding:7px 12px 7px 0; font-weight:bold; color:#333;
                       white-space:nowrap; vertical-align:top;">Fald fra top</td>
            <td style="padding:7px 0; line-height:1.6;">
              Procentvis fald fra HWM til aktuel kurs: (aktuel / HWM − 1) × 100.
              Du modtager denne advarsel når faldet overstiger {trail_pct}%.
            </td>
          </tr>
          <tr style="border-top:1px solid #eee;">
            <td style="padding:7px 12px 7px 0; font-weight:bold; color:#333;
                       white-space:nowrap; vertical-align:top;">1M afkast</td>
            <td style="padding:7px 0; line-height:1.6;">
              Fondens officielle afkast de seneste 30 dage fra PFA's faktaark.
              Positivt 1M afkast trods Trail Stop kan betyde en normal korrektion
              i en ellers stigende fond. Negativt 1M afkast kombineret med Trail Stop
              er et stærkere salgssignal.
            </td>
          </tr>
          <tr style="border-top:1px solid #eee;">
            <td style="padding:7px 12px 7px 0; font-weight:bold; color:#333;
                       white-space:nowrap; vertical-align:top;">Rank</td>
            <td style="padding:7px 0; line-height:1.6;">
              Fondens placering i hele PFA-universet ({total_funds} fonde) rangeret
              efter 1M afkast. Rank #1 er den stærkeste fond denne måned. Hvis din
              fond er faldet til rank #20+, løber mange andre fonde hurtigere — det
              er et signal om at det kan betale sig at rotere til en stærkere fond.
            </td>
          </tr>
          <tr style="border-top:1px solid #eee;">
            <td style="padding:7px 12px 7px 0; font-weight:bold; color:#333;
                       white-space:nowrap; vertical-align:top;">Afkast fra køb</td>
            <td style="padding:7px 0; line-height:1.6;">
              Dit samlede afkast siden købsdato: (aktuel kurs / købspris − 1) × 100.
              Selv med en Trail Stop advarsel kan dit totale afkast stadig være positivt.
              Det er vigtigt at skelne mellem "fonden falder fra sin top" og
              "jeg taber penge på min investering".
            </td>
          </tr>
          <tr style="border-top:1px solid #eee;">
            <td style="padding:7px 12px 7px 0; font-weight:bold; color:#333;
                       white-space:nowrap; vertical-align:top;">Trail Stop tærskel</td>
            <td style="padding:7px 0; line-height:1.6;">
              Aktuelt sat til {trail_pct}%. Tærsklen er valgt til at fange reelle
              momentum-skift uden at generere for mange falske alarmer ved normal
              daglig markedsvolatilitet. Overvej at justere tærsklen op hvis du
              ejer volatile fonde som guld eller emerging markets.
            </td>
          </tr>
        </table>
      </div>
    </div>

    <!-- FOOTER -->
    <div style="padding:15px 30px; background:#f8f9fa; border-top:1px solid #eee;
                font-size:12px; color:#999;">
      Sendt automatisk fra TrendAgent · GitHub Actions · {now}
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

    alerts = find_trail_stop_alerts(
        portfolio, latest_list, latest_map, hwm_data, args.trail_pct
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
