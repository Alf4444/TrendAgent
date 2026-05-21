"""
etf_send_alert.py — Mail-alarm for ETF Spejder
================================================
Sendes på hverdage hvis der er:
  🔴 Trail Stop-advarsler (fald fra HWM over tærskel)
  🟡 Momentum-advarsler  (ejede fonde med aftagende momentum: ↑↓ eller ↓↓)
  🟢 Nye Spejder-hits    (nye hurtige eller stabile kandidater)

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

# Tilføj reporting/ til Python-stien så utils.py kan importeres
sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import check_trail_stop, get_trail_stop_pct

ROOT           = Path(__file__).resolve().parents[1]
HITS_FILE      = ROOT / "data/etf_spejder_hits.json"
PREV_FILE      = ROOT / "data/etf_spejder_prev.json"
HWM_FILE       = ROOT / "data/etf_hwm.json"
PORTFOLIO_FILE = ROOT / "config/etf_portfolio.json"
LATEST_FILE    = ROOT / "data/etf_latest.json"

# Momentum-pile der signalerer aftagende momentum for ejede fonde
MOMENTUM_WARN_PILES  = {'↑↓', '↓↓'}
MOMENTUM_FILE        = ROOT / "data/etf_momentum_alerts.json"
MOMENTUM_DOWN_PCT    = 10.0   # K2: momentum under denne % → signal


# ==========================================
# FIL-HJÆLPEFUNKTIONER
# ==========================================

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

def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ==========================================
# TRAIL STOP — via utils (enkelt kilde til sandhed)
# ==========================================

def get_trail_alerts(portfolio, latest_map, hwm_data):
    """
    Gennemgår aktive positioner og finder trail stop-brud.
    Bruger utils.check_trail_stop() og utils.get_trail_stop_pct()
    så logikken er identisk med etf_build_weekly.py.

    Opdaterer HWM-data in-place og returnerer:
      (trail_alerts, opdateret hwm_data)
    """
    today_str    = datetime.now().strftime('%Y-%m-%d')
    trail_alerts = []

    for isin, p_info in portfolio.items():
        if not p_info.get('active', False):
            continue

        buy_price = p_info.get('buy_price', 0)
        if not buy_price:
            continue

        if isin not in latest_map:
            continue

        curr_price = latest_map[isin].get('nav', 0)
        if not curr_price:
            continue

        volatility     = latest_map[isin].get('volatility')
        total_ret_pct  = round(((curr_price / buy_price) - 1) * 100, 2) if buy_price else None
        rsi            = rsi_map.get(isin) if 'rsi_map' in dir() else None
        trail_pct      = get_trail_stop_pct(volatility, rsi, total_return_pct=total_ret_pct)

        hwm_entry, alert = check_trail_stop(
            isin, curr_price, buy_price, hwm_data, today_str, trail_pct
        )
        hwm_data[isin] = hwm_entry

        if alert:
            alert['name']         = p_info.get('name', isin)
            alert['ticker']       = p_info.get('ticker', '')
            alert['depot']        = p_info.get('depot', '')
            alert['ask_eligible'] = p_info.get('ask_eligible')
            alert['trail_pct']    = trail_pct
            trail_alerts.append(alert)
            print(
                f"🔔 TRAIL STOP: {alert['name']} faldet {alert['fall_pct']}% "
                f"fra top {alert['hwm']} → nu {alert['curr']} "
                f"(tærskel: {trail_pct}%)"
            )

    return trail_alerts, hwm_data


# ==========================================
# ROTATION-ALTERNATIVER — til K2/K3 signaler
# ==========================================

def get_rotation_alternatives(isin, portfolio, hits_data, latest_map, n=3):
    """
    Finder top-N Spejder-kandidater som rotationsalternativer.
    Sorteret på momentum (stærkest først).
    Tilføjer sektor og eksponerings-note (ny eksponering / samme sektor som X).

    Returnerer liste af dicts med: name, ticker, momentum, category, exposure_note
    """
    owned_isins = {i for i, p in portfolio.items() if p.get('active', False)}
    # Byg kategori-map for ejede fonde fra latest_map
    owned_category_map = {}
    for i, p in portfolio.items():
        if p.get('active', False):
            cat = latest_map.get(i, {}).get('category', '') or p.get('category', '')
            if cat:
                owned_category_map[i] = cat

    # Saml alle hits — sortér på momentum
    all_hits = (
        hits_data.get('hits_hurtige', []) +
        hits_data.get('hits_stabile', []) +
        hits_data.get('hits', [])
    )
    # Deduplikér på ISIN
    seen = set()
    unique_hits = []
    for h in all_hits:
        h_isin = h.get('isin')
        if h_isin and h_isin not in seen and h_isin not in owned_isins:
            seen.add(h_isin)
            unique_hits.append(h)

    # Sortér på momentum — stærkest først
    unique_hits.sort(key=lambda x: x.get('momentum', 0), reverse=True)

    alternatives = []
    for h in unique_hits[:n]:
        h_isin    = h.get('isin', '')
        h_cat     = latest_map.get(h_isin, {}).get('category', '') or h.get('category', '')

        # Find ejede fonde i samme kategori
        same_cat_owned = []
        if h_cat:
            for oi, oc in owned_category_map.items():
                if oi != isin and h_cat and oc and h_cat.lower() in oc.lower():
                    same_cat_owned.append(portfolio[oi].get('ticker', oi))

        if same_cat_owned:
            exposure_note = f"samme sektor som {' og '.join(same_cat_owned)}"
        else:
            exposure_note = "ny eksponering"

        alternatives.append({
            'name':          h.get('name', ''),
            'ticker':        h.get('ticker', ''),
            'momentum':      h.get('momentum', 0),
            'category':      h_cat or '—',
            'exposure_note': exposure_note,
        })

    return alternatives


# ==========================================
# MOMENTUM SVÆKKES — K1/K2/K3 signal for ejede fonde
# ==========================================

def load_momentum_alerts():
    """Indlæser anti-spam fil. Format: {isin: {kriterium: dato}}"""
    if not MOMENTUM_FILE.exists():
        return {}
    try:
        with open(MOMENTUM_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_momentum_alerts(data):
    """Gemmer anti-spam fil."""
    MOMENTUM_FILE.parent.mkdir(exist_ok=True)
    with open(MOMENTUM_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_momentum_svækkes_alerts(portfolio, hits_data, prev_data, latest_map, n_alternatives=3):
    """
    Detekterer ejede fonde der mister momentum via tre kriterier.
    Første kriterium der rammes sender signalet — ikke alle tre.

    K1 — Pile: consecutive_down=True i hits (↓↓ to kørsler i træk)
    K2 — Momentum: momentum % under MOMENTUM_DOWN_PCT (10%)
    K3 — Univers: fond ikke i Spejderens top-200 (hits)

    Anti-spam: samme fond + samme kriterium sender ikke igen
    før kriteriet har ændret sig (gemmes i etf_momentum_alerts.json).

    Returnerer: (alerts, opdateret_spam_data)
    """
    today_str  = datetime.now().strftime('%Y-%m-%d')
    spam_data  = load_momentum_alerts()
    alerts     = []

    owned_isins = {
        isin: p for isin, p in portfolio.items()
        if p.get('active', False)
    }
    if not owned_isins:
        return [], spam_data

    # Byg lookup fra alle hits (200 fonde)
    all_hits_isins = {
        h.get('isin') for h in (
            hits_data.get('hits', []) +
            hits_data.get('hits_hurtige', []) +
            hits_data.get('hits_stabile', [])
        ) if h.get('isin')
    }

    # Byg ISIN → hit-data map for ejede fonde
    all_hits_map = {}
    for h in (hits_data.get('hits', []) + hits_data.get('hits_hurtige', []) + hits_data.get('hits_stabile', [])):
        if h.get('isin') and h['isin'] not in all_hits_map:
            all_hits_map[h['isin']] = h

    for isin, p_info in owned_isins.items():
        hit       = all_hits_map.get(isin)
        item      = latest_map.get(isin, {})
        navn      = p_info.get('name', isin)
        ticker    = p_info.get('ticker', '')
        depot     = p_info.get('depot', '')
        momentum  = (hit or {}).get('momentum') or item.get('return_1m')

        # Find kriterium — første der rammer
        kriterium = None
        detalje   = ''

        # K1: consecutive_down i hits
        if hit and hit.get('consecutive_down'):
            kriterium = 'K1'
            detalje   = f'pile ↓↓ to kørsler i træk (momentum: {momentum:+.1f}%)' if momentum is not None else 'pile ↓↓ to kørsler i træk'

        # K2: momentum under grænse
        elif momentum is not None and momentum < MOMENTUM_DOWN_PCT:
            kriterium = 'K2'
            detalje   = f'momentum {momentum:+.1f}% — under {MOMENTUM_DOWN_PCT}% over MA'

        # K3: ude af top-200
        elif isin not in all_hits_isins:
            kriterium = 'K3'
            detalje   = 'ikke længere i Spejderens top-200 kandidater'

        if not kriterium:
            # Ingen kriterium ramt — nulstil evt. spam-registrering
            if isin in spam_data:
                spam_data.pop(isin, None)
            continue

        # Anti-spam: tjek om samme fond + kriterium allerede er sendt
        prev_alert = spam_data.get(isin, {})
        if prev_alert.get('kriterium') == kriterium:
            print(f"   ⏭️  {navn}: {kriterium} allerede sendt — springer over")
            continue

        # Rotation-alternativer til K2 og K3
        alternatives = []
        if kriterium in ('K2', 'K3'):
            alternatives = get_rotation_alternatives(
                isin, portfolio, hits_data, latest_map, n=n_alternatives
            )

        # Nyt signal — registrér og tilføj
        spam_data[isin] = {'kriterium': kriterium, 'dato': today_str}
        alerts.append({
            'isin':         isin,
            'name':         navn,
            'ticker':       ticker,
            'depot':        depot,
            'ask_eligible': p_info.get('ask_eligible'),
            'kriterium':    kriterium,
            'detalje':      detalje,
            'momentum':     momentum,
            'alternatives': alternatives,
        })
        print(f"   📉 MOMENTUM SVÆKKES: {navn} — {kriterium}: {detalje}")

    # Sortér K1 øverst, K2 midt, K3 nederst
    alerts.sort(key=lambda x: x['kriterium'])

    return alerts, spam_data


# ==========================================
# MOMENTUM-ALARM — ejede fonde med aftagende momentum
# ==========================================

def get_momentum_alerts(portfolio, hits_data, prev_data):
    """
    Finder ejede fonde med aftagende momentum (↑↓ eller ↓↓).

    Strategi:
      1. Byg et map over ejede tickers fra portfolio
      2. Søg i hits (alle 200) + prev hits for ejede fonde
      3. Sammenlign momentum_pile — advar hvis ↑↓ eller ↓↓

    Returnerer liste af alert-dicts.
    """
    owned_ticker_map = {
        p.get('ticker', '').upper(): (isin, p)
        for isin, p in portfolio.items()
        if p.get('active', False) and p.get('ticker')
    }

    if not owned_ticker_map:
        return []

    # Saml alle hits (top 10 + resten af de 200) fra begge filer
    all_curr = hits_data.get('hits', []) + hits_data.get('hits_hurtige', []) + hits_data.get('hits_stabile', [])
    all_prev = prev_data.get('hits', []) + prev_data.get('hits_hurtige', []) + prev_data.get('hits_stabile', [])

    # Deduplikér på ticker
    curr_map = {}
    for h in all_curr:
        t = h.get('ticker', '').upper()
        if t and t not in curr_map:
            curr_map[t] = h

    prev_map = {}
    for h in all_prev:
        t = h.get('ticker', '').upper()
        if t and t not in prev_map:
            prev_map[t] = h

    alerts = []
    for ticker, (isin, p_info) in owned_ticker_map.items():
        curr = curr_map.get(ticker)
        prev = prev_map.get(ticker)

        if not curr and not prev:
            # Fonden er ikke i Spejderens univers denne kørsel
            continue

        pile = (curr or prev or {}).get('momentum_pile', '—')

        if pile in MOMENTUM_WARN_PILES:
            curr_mom  = (curr or {}).get('momentum')
            prev_mom  = (prev or {}).get('momentum')
            curr_score = (curr or {}).get('score')

            alerts.append({
                'isin':       isin,
                'name':       p_info.get('name', isin),
                'ticker':     ticker,
                'depot':      p_info.get('depot', ''),
                'pile':       pile,
                'momentum':   curr_mom,
                'prev_momentum': prev_mom,
                'score':      curr_score,
                'rsi':        (curr or {}).get('rsi'),
                'return_1m':  (curr or {}).get('return_1m'),
            })
            print(
                f"🟡 MOMENTUM ADVARSEL: {p_info.get('name', isin)} "
                f"pile={pile} momentum={curr_mom} (prev={prev_mom})"
            )

    return alerts


# ==========================================
# ROTATIONSFORSLAG — baseret på score + momentum
# ==========================================

def get_rotation_suggestion(portfolio, latest_map, hits_data, momentum_alerts, trail_alerts):
    """
    Finder det bedste rotationsforslag:
      Sælg: svagest ejet fond (lavest score/momentum, eller dem med advarsel)
      Køb:  bedste nye hurtige kandidat der ikke allerede ejes

    Returnerer (weakest_dict, best_new_dict) eller (None, None).
    """
    active_isins = {isin for isin, p in portfolio.items() if p.get('active', False)}
    owned_tickers = {p.get('ticker', '').upper() for isin, p in portfolio.items() if p.get('active', False)}

    # Svagest ejet: prioritér trail stop > momentum-advarsel > lavest 1M
    trail_isins    = {a['isin'] for a in trail_alerts}
    momentum_isins = {a['isin'] for a in momentum_alerts}

    candidates = []
    for isin, p_info in portfolio.items():
        if not p_info.get('active', False):
            continue
        item      = latest_map.get(isin, {})
        return_1m = item.get('return_1m') or 0

        # Prioritetsscore: trail=0, momentum=1, resten=2+
        if isin in trail_isins:
            prio = 0
        elif isin in momentum_isins:
            prio = 1
        else:
            prio = 2

        candidates.append({
            'isin':      isin,
            'name':      p_info.get('name', isin),
            'ticker':    p_info.get('ticker', ''),
            'return_1m': return_1m,
            'prio':      prio,
        })

    if not candidates:
        return None, None

    weakest = sorted(candidates, key=lambda x: (x['prio'], x['return_1m']))[0]

    # Bedste nye hurtige hest der ikke ejes
    nye_hits = hits_data.get('hits_nye', [])
    best_new = next(
        (h for h in nye_hits if h.get('ticker', '').upper() not in owned_tickers),
        None
    )
    # Fallback: bedste hurtige hit overhovedet der ikke ejes
    if not best_new:
        best_new = next(
            (h for h in hits_data.get('hits_hurtige', [])
             if h.get('ticker', '').upper() not in owned_tickers),
            None
        )

    return weakest, best_new


# ==========================================
# HTML-MAIL BYGNING
# ==========================================

def _pile_html(pile):
    """Returnerer farvet pile-html."""
    colors = {'↑↑': '#1e8e3e', '↓↑': '#1e8e3e', '↑↓': '#f59c00', '↓↓': '#d93025'}
    color  = colors.get(pile, '#888')
    return f'<span style="font-weight:700; color:{color};">{pile}</span>' if pile and pile != '—' else '<span style="color:#ccc;">—</span>'


def _depot_badges(ask_eligible):
    """Returnerer HTML med depot-egnethedsbadges for alle 6 depoter."""
    badge_style = "display:inline-block; padding:1px 6px; border-radius:8px; font-size:10px; font-weight:700; margin-right:3px; margin-top:2px;"
    ask_ok  = f'background:#e6f4ea; color:#1e6e34; border:1px solid #a8d5b5; {badge_style}'
    ask_no  = f'background:#fff3e0; color:#e65100; border:1px solid #ffcc80; {badge_style}'

    ask_badge = (f'<span style="{ask_ok}">ASK ✓</span>' if ask_eligible
                 else f'<span style="{ask_no}">ASK ✗</span>')
    always = ''.join([
        f'<span style="{ask_ok}">{d} ✓</span>'
        for d in ['AKT', 'AOP', 'KPP', 'SpSj-RTP', 'SpSj-INV']
    ])
    return ask_badge + always


def build_email_html(trail_alerts, momentum_alerts, momentum_svækkes, nye_hits, nye_stabile,
                     rotation_weakest, rotation_best_new, hits_data):
    """Bygger HTML-indhold til alarm-mailen."""
    now = datetime.now().strftime('%d-%m-%Y %H:%M')

    # ---- 🔴 Trail Stop ----
    trail_html = ""
    if trail_alerts:
        rows = ""
        for a in trail_alerts:
            rows += f"""
            <tr>
              <td style="padding:8px; border-bottom:1px solid #fde;">{a.get('name','?')}<br>
                <small style="color:#888;">{a.get('ticker','')} · {a.get('depot','')}</small><br>
                {_depot_badges(a.get('ask_eligible'))}</td>
              <td style="padding:8px; border-bottom:1px solid #fde; color:#d93025; font-weight:700;">{a['fall_pct']:+.1f}%</td>
              <td style="padding:8px; border-bottom:1px solid #fde;">HWM: {a['hwm']} → Nu: {a['curr']}</td>
              <td style="padding:8px; border-bottom:1px solid #fde; color:#888;">
                Stop ved: {a['trail_pct']}% · Afkast fra køb: {a['total_ret']:+.1f}%
              </td>
            </tr>"""
        trail_html = f"""
        <div style="margin-bottom:20px;">
          <h3 style="color:#d93025; margin:0 0 8px;">🔴 Trail Stop — sælg overvej nu ({len(trail_alerts)})</h3>
          <table style="width:100%; border-collapse:collapse; font-size:13px; background:#fff5f5; border-radius:6px;">
            <tr style="background:#fde;"><th style="padding:8px; text-align:left;">Fond</th>
              <th style="padding:8px; text-align:left;">Fald fra top</th>
              <th style="padding:8px; text-align:left;">Kurs</th>
              <th style="padding:8px; text-align:left;">Detaljer</th></tr>
            {rows}
          </table>
        </div>"""

    # ---- 🟡 Momentum-advarsler ----
    momentum_html = ""
    if momentum_alerts:
        rows = ""
        for a in momentum_alerts:
            prev_str = f"{a['prev_momentum']:+.1f}%" if a.get('prev_momentum') is not None else "–"
            curr_str = f"{a['momentum']:+.1f}%" if a.get('momentum') is not None else "–"
            rsi_str  = f"{a['rsi']:.0f}" if a.get('rsi') else "–"
            rows += f"""
            <tr>
              <td style="padding:8px; border-bottom:1px solid #fef3cd;">{a['name']}<br>
                <small style="color:#888;">{a['ticker']} · {a.get('depot','')}</small></td>
              <td style="padding:8px; border-bottom:1px solid #fef3cd;">{_pile_html(a['pile'])}</td>
              <td style="padding:8px; border-bottom:1px solid #fef3cd;">{prev_str} → {curr_str}</td>
              <td style="padding:8px; border-bottom:1px solid #fef3cd; color:#888;">RSI {rsi_str}</td>
            </tr>"""
        momentum_html = f"""
        <div style="margin-bottom:20px;">
          <h3 style="color:#f59c00; margin:0 0 8px;">🟡 Momentum aftager — hold øje ({len(momentum_alerts)})</h3>
          <table style="width:100%; border-collapse:collapse; font-size:13px; background:#fffdf0; border-radius:6px;">
            <tr style="background:#fef3cd;"><th style="padding:8px; text-align:left;">Fond</th>
              <th style="padding:8px; text-align:left;">Pile</th>
              <th style="padding:8px; text-align:left;">Momentum</th>
              <th style="padding:8px; text-align:left;">RSI</th></tr>
            {rows}
          </table>
        </div>"""

    # ---- 📉 Momentum svækkes ----
    svækkes_html = ""
    if momentum_svækkes:
        items_html = ""
        for a in momentum_svækkes:
            mom_str  = f"{a['momentum']:+.1f}%" if a.get('momentum') is not None else "–"
            k_color  = {"K1": "#d93025", "K2": "#f59c00", "K3": "#888"}.get(a['kriterium'], "#888")
            k_badge  = f'<span style="font-weight:700; color:{k_color}; background:#f5f5f5; padding:1px 6px; border-radius:4px; font-size:12px;">{a["kriterium"]}</span>'

            # Hoved-linje
            items_html += f"""
            <div style="margin-bottom:14px; padding:10px 12px; background:#fef9f0; border-left:3px solid {k_color}; border-radius:0 4px 4px 0;">
              <div style="font-size:13px; font-weight:600;">{k_badge}&nbsp; {a['name']} <span style="color:#888; font-weight:400;">({a['ticker']} · {a.get('depot','')})</span></div>
              <div style="font-size:12px; color:#555; margin-top:3px;">{a['detalje']}</div>
              <div style="margin-top:5px;">{_depot_badges(a.get('ask_eligible'))}</div>"""

            # K1: kun advarselstekst
            if a['kriterium'] == 'K1':
                items_html += """
              <div style="font-size:11px; color:#888; margin-top:4px; font-style:italic;">Ingen handling endnu — hold ekstra øje de næste dage.</div>"""

            # K2/K3: rotation-alternativer
            elif a.get('alternatives'):
                items_html += """
              <div style="font-size:11px; color:#555; margin-top:6px; font-weight:600;">Mulige alternativer:</div>"""
                for alt in a['alternatives']:
                    exp_color = "#888" if "samme sektor" in alt['exposure_note'] else "#1e8e3e"
                    items_html += f"""
              <div style="font-size:12px; color:#333; margin-top:3px; padding-left:8px;">
                · <strong>{alt['name']}</strong> ({alt['ticker']}) <span style="color:#1e8e3e; font-weight:700;">{alt['momentum']:+.1f}%</span>
                · <span style="color:#555;">{alt['category']}</span>
                — <span style="color:{exp_color}; font-size:11px;">{alt['exposure_note']}</span>
              </div>"""

            items_html += "\n            </div>"

        svækkes_html = f"""
        <div style="margin-bottom:20px;">
          <h3 style="color:#e67e22; margin:0 0 8px;">📉 Momentum svækkes — overvej rotation ({len(momentum_svækkes)})</h3>
          {items_html}
          <div style="font-size:11px; color:#888; margin-top:4px; padding:4px 8px; background:#fef9f0; border-radius:4px;">
            K1 = ↓↓ to kørsler i træk · K2 = momentum under 10% · K3 = ude af top-200 · Information — ingen handling påkrævet
          </div>
        </div>"""

    # ---- 🟢 Nye Spejder-hits ----
    hits_html = ""
    alle_nye = list(nye_hits) + list(nye_stabile)
    if alle_nye:
        rows = ""
        for h in alle_nye:
            kat     = "🚀" if h.get('kategori') == 'hurtig' else "📈"
            rsi_w   = f" ⚠️" if h.get('rsi') and h['rsi'] >= 70 else ""
            golden  = " 🚀 GOLDEN" if h.get('cross') == "🚀 GOLDEN" else ""
            rows += f"""
            <tr>
              <td style="padding:8px; border-bottom:1px solid #eee;">{kat} <strong>{h['name']}</strong><br>
                <small style="color:#888;">{h.get('ticker','')} · Score: {h.get('score','–')}pt</small><br>
                {_depot_badges(h.get('ask_eligible'))}</td>
              <td style="padding:8px; border-bottom:1px solid #eee; font-weight:700; color:#1e8e3e;">
                +{h['momentum']:.1f}%</td>
              <td style="padding:8px; border-bottom:1px solid #eee;">
                {f"+{h['return_1y']:.1f}%" if h.get('return_1y') else '–'}</td>
              <td style="padding:8px; border-bottom:1px solid #eee;">
                {f"{h['rsi']:.0f}" if h.get('rsi') else '–'}{rsi_w}{golden}</td>
              <td style="padding:8px; border-bottom:1px solid #eee; color:#888; font-size:11px;">
                TER: {h.get('ter','–')}%</td>
            </tr>"""
        hits_html = f"""
        <div style="margin-bottom:20px;">
          <h3 style="color:#1e8e3e; margin:0 0 8px;">🟢 Nye Spejder-kandidater ({len(alle_nye)})</h3>
          <table style="width:100%; border-collapse:collapse; font-size:13px;">
            <tr style="background:#f5f5f5;"><th style="padding:8px; text-align:left;">Fond</th>
              <th style="padding:8px; text-align:left;">Momentum</th>
              <th style="padding:8px; text-align:left;">1Y afkast</th>
              <th style="padding:8px; text-align:left;">RSI</th>
              <th style="padding:8px; text-align:left;">TER</th></tr>
            {rows}
          </table>
        </div>"""

    # ---- 🔄 Rotationsforslag ----
    rotation_html = ""
    if rotation_weakest and rotation_best_new:
        pile_w = rotation_weakest.get('pile', '')
        reason = "trail stop-advarsel" if rotation_weakest.get('prio') == 0 \
            else "aftagende momentum" if rotation_weakest.get('prio') == 1 \
            else f"{rotation_weakest.get('return_1m', 0):+.1f}% seneste måned"
        rotation_html = f"""
        <div style="background:#fff8e1; border-left:4px solid #f59c00; padding:12px 16px; margin:0 0 20px; border-radius:0 4px 4px 0;">
          <strong>🔄 Mulig rotation</strong><br>
          <span style="font-size:13px;">
            Overvej at sælge <strong>{rotation_weakest['name']}</strong> ({reason})
            og købe <strong>{rotation_best_new['name']}</strong>
            (+{rotation_best_new['momentum']:.1f}% momentum
            {f", +{rotation_best_new['return_1y']:.1f}% 1Y" if rotation_best_new.get('return_1y') else ""}).
          </span><br>
          <small style="color:#888;">Tjek RSI og Trail Stop inden handel. En advarsel er ikke automatisk et signal.</small>
        </div>"""

    has_content = trail_html or momentum_html or svækkes_html or hits_html

    return f"""
    <html><body style="font-family: Arial, sans-serif; max-width:700px; margin:0 auto; color:#2c3e50;">
      <div style="background:linear-gradient(135deg,#1a1a2e,#16213e); color:white; padding:20px 24px; border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">📡 TrendAgent ETF Alarm</h2>
        <p style="margin:4px 0 0; color:#aaa; font-size:12px;">{now}</p>
      </div>
      <div style="background:white; padding:20px 24px; border:1px solid #eee; border-radius:0 0 8px 8px;">
        {"<p style='color:#888;'>Ingen aktuelle advarsler.</p>" if not has_content else ""}
        {trail_html}
        {momentum_html}
        {svækkes_html}
        {hits_html}
        {rotation_html}
        <hr style="margin:20px 0; border:none; border-top:1px solid #eee;">
        <p style="font-size:11px; color:#aaa;">
          Se fuld rapport: <a href="https://alf4444.github.io/TrendAgent/build/etf_weekly.html">ETF Weekly</a><br>
          Alarm-frekvens: Hverdage · Trail Stop: Variabelt 3–7% baseret på volatilitet
        </p>
      </div>
    </body></html>
    """


# ==========================================
# MAIL-AFSENDELSE
# ==========================================

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


# ==========================================
# HOVEDFUNKTION
# ==========================================

def main():
    print("\n" + "="*50)
    print("📡 ETF SEND ALERT")
    print("="*50)

    hits_data = load_json(HITS_FILE, {})
    prev_data = load_json(PREV_FILE, {})
    portfolio = load_json(PORTFOLIO_FILE, {})
    latest    = load_json(LATEST_FILE, [])
    hwm_data  = load_json(HWM_FILE, {})

    latest_map = {item['isin']: item for item in latest} if isinstance(latest, list) else {}

    # ---- 🔴 Trail Stop (via utils — opdaterer HWM) ----
    trail_alerts, hwm_data = get_trail_alerts(portfolio, latest_map, hwm_data)

    # Gem opdateret HWM tilbage til fil
    save_json(HWM_FILE, hwm_data)

    # ---- 🟡 Momentum-advarsler for ejede fonde ----
    momentum_alerts = get_momentum_alerts(portfolio, hits_data, prev_data)

    # ---- 📉 Momentum svækkes (K1/K2/K3) ----
    momentum_svækkes, spam_data = get_momentum_svækkes_alerts(
        portfolio, hits_data, prev_data, latest_map
    )
    save_momentum_alerts(spam_data)

    # ---- 🟢 Nye Spejder-hits ----
    # Nye hurtige heste
    nye_hits    = hits_data.get('hits_nye', []) if isinstance(hits_data, dict) else []
    # Nye stabile: is_new_this_week=True i hits_stabile
    nye_stabile = [
        h for h in hits_data.get('hits_stabile', [])
        if h.get('is_new_this_week', False)
    ] if isinstance(hits_data, dict) else []

    # ---- 🔄 Rotationsforslag ----
    rotation_weakest, rotation_best_new = get_rotation_suggestion(
        portfolio, latest_map, hits_data, momentum_alerts, trail_alerts
    )

    # Ingen mail hvis ingenting at rapportere
    if not trail_alerts and not momentum_alerts and not momentum_svækkes and not nye_hits and not nye_stabile:
        print("✅ Ingen advarsler eller nye hits — ingen mail sendes")
        return

    # Byg subject
    subject_parts = []
    if trail_alerts:
        subject_parts.append(f"🔴 {len(trail_alerts)} Trail Stop")
    if momentum_alerts:
        subject_parts.append(f"🟡 {len(momentum_alerts)} Momentum")
    if momentum_svækkes:
        subject_parts.append(f"📉 {len(momentum_svækkes)} Svækkes")
    if nye_hits or nye_stabile:
        n = len(nye_hits) + len(nye_stabile)
        subject_parts.append(f"🟢 {n} nye hits")

    subject = f"📡 TrendAgent ETF — {' · '.join(subject_parts)}"

    html = build_email_html(
        trail_alerts, momentum_alerts, momentum_svækkes, nye_hits, nye_stabile,
        rotation_weakest, rotation_best_new, hits_data
    )
    send_mail(subject, html)

    print(f"   Trail Stop:        {len(trail_alerts)}")
    print(f"   Momentum-advarsler:{len(momentum_alerts)}")
    print(f"   Momentum svækkes:  {len(momentum_svækkes)}")
    print(f"   Nye hurtige hits:  {len(nye_hits)}")
    print(f"   Nye stabile hits:  {len(nye_stabile)}")
    print("="*50)


if __name__ == "__main__":
    main()
