"""
ai_analysis.py — AI-tekstanalyse til TrendAgent
=================================================
Genererer læsbar dansk tekst baseret på porteføljedata.
Bruges i alarm-mail og ETF Weekly rapport.

Kræver: ANTHROPIC_API_KEY som miljøvariabel (GitHub Secret)

Modes:
  "alarm"  — reaktiv tekst, tone skalerer med signalernes alvorlighed
  "weekly" — opsummerende tekst, rolig analytisk tone

Kaldes fra:
  etf_send_alert.py  → mode="alarm"
  etf_build_weekly.py → mode="weekly"
"""

import json
import os
import urllib.request
import urllib.error

# Model — Haiku er billig og hurtig nok til denne opgave
MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
MAX_TOKENS = 400


# ==========================================
# PAYLOAD-BYGGER
# ==========================================

def build_payload(portfolio, latest_map, hits_data, hwm_data,
                  trail_alerts=None, momentum_svækkes=None,
                  corr_pairs=None, heatmap_data=None):
    """
    Bygger det dataobjekt der sendes til Claude API.
    Inkluderer kun det der er relevant — holder payload kompakt.
    """

    # --- Ejede positioner ---
    positioner = []
    for isin, p in portfolio.items():
        if not p.get('active', False):
            continue
        latest = latest_map.get(isin, {})
        hwm    = hwm_data.get(isin, {})
        buy    = p.get('buy_price', 0)
        curr   = latest.get('nav', 0)
        afkast = round(((curr / buy) - 1) * 100, 1) if buy and curr else None
        hwm_val = hwm.get('hwm', 0)
        hwm_afstand = round(((curr / hwm_val) - 1) * 100, 1) if hwm_val and curr else None

        positioner.append({
            'ticker':      p.get('ticker', isin),
            'navn':        p.get('name', isin),
            'sektor':      latest.get('category', p.get('category', '—')),
            'depot':       p.get('depot', '—'),
            'afkast_pct':  afkast,
            'hwm_afstand': hwm_afstand,
            'ask_egnet':   p.get('ask_eligible', False),
        })

    # --- Aktive signaler ---
    signaler = []
    if trail_alerts:
        for t in trail_alerts:
            signaler.append({
                'type':   'Trail Stop',
                'fond':   t.get('name', ''),
                'detalje': f"Faldet {t.get('fall_pct', '')}% fra top"
            })
    if momentum_svækkes:
        for m in momentum_svækkes:
            k = m.get('kriterium', '')
            signaler.append({
                'type':    k,
                'fond':    m.get('name', m.get('ticker', '')),
                'detalje': f"Momentum: {m.get('momentum', '')}%"
            })

    # --- Porteføljerisiko ---
    risiko = {}
    if heatmap_data:
        sektorer = {}
        for sektor, data in heatmap_data.items():
            if isinstance(data, dict) and data.get('pct'):
                sektorer[sektor] = data['pct']
        risiko['sektor_fordeling'] = sektorer

    if corr_pairs:
        høj_korr = [
            f"{p.get('a_ticker','')}/{p.get('b_ticker','')}: {p.get('correlation','')}"
            for p in corr_pairs
            if isinstance(p.get('correlation'), float) and p['correlation'] >= 0.85
        ]
        if høj_korr:
            risiko['høj_korrelation'] = høj_korr

    # --- Kandidater fra Spejderen ---
    kandidater = []
    if isinstance(hits_data, dict):
        alle = hits_data.get('hits_hurtige', [])[:5] + hits_data.get('hits_stabile', [])[:3]
        for h in alle:
            kandidater.append({
                'ticker':     h.get('ticker', ''),
                'navn':       h.get('name', '')[:40],
                'kategori':   h.get('kategori', ''),
                'momentum':   h.get('momentum', ''),
                'sektor':     h.get('category', ''),
                'ask_egnet':  h.get('ask_eligible', False),
                'er_ny':      h.get('is_new_this_week', False),
            })

    return {
        'positioner':  positioner,
        'signaler':    signaler,
        'risiko':      risiko,
        'kandidater':  kandidater,
    }


# ==========================================
# PROMPTS
# ==========================================

SYSTEM_ALARM = """Du er en kortfattet, dansk porteføljeassistent for en privat investor.
Du modtager porteføljedata og signaler i JSON-format og skriver 3-5 sætninger på dansk.

Tone skalerer med alvorlighed:
- Ingen signaler / nye kandidater: rolig og informerende
- K1: opmærksom, "hold øje med"
- K2: tydelig, "bør overvejes"
- K3 eller Trail Stop: direkte, "handling relevant"

Regler:
- Skriv kun dansk, ingen markdown, ingen bullet points
- Nævn altid hvilken fond signalet handler om
- Hvis der er gode ASK-egnede kandidater til rotation, nævn dem specifikt
- Max 5 sætninger
- Undgå finansiel rådgivning — beskriv hvad dataene viser"""

SYSTEM_WEEKLY = """Du er en kortfattet, dansk porteføljeassistent for en privat investor.
Du modtager ugens porteføljedata i JSON-format og skriver et overblik på dansk.

Tone: rolig, analytisk, som en ugentlig status-opdatering.

Regler:
- Skriv kun dansk, ingen markdown, ingen bullet points
- Start med porteføljens overordnede tilstand
- Nævn koncentrationsrisiko hvis sektorer er over 40%
- Nævn de stærkeste og svageste positioner
- Afslut med 1 sætning om de bedste kandidater til rotation hvis relevant
- Max 6 sætninger
- Undgå finansiel rådgivning — beskriv hvad dataene viser"""

USER_ALARM = """Her er dagens porteføljedata og signaler:

{payload}

Skriv en kort analyse til alarm-mailen. Tonen skal matche alvorligheden af signalerne."""

USER_WEEKLY = """Her er ugens porteføljedata:

{payload}

Skriv et kort overblik til den ugentlige rapport."""


# ==========================================
# API-KALD
# ==========================================

def call_claude(system_prompt, user_prompt):
    """
    Kalder Anthropic API og returnerer tekstsvar.
    Returnerer None ved fejl — så integration ikke crasher.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        print("⚠️  ANTHROPIC_API_KEY mangler — AI-analyse springes over")
        return None

    body = json.dumps({
        "model":      MODEL,
        "max_tokens": MAX_TOKENS,
        "system":     system_prompt,
        "messages":   [{"role": "user", "content": user_prompt}]
    }).encode('utf-8')

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            tekst = data.get('content', [{}])[0].get('text', '').strip()
            print(f"✅ AI-analyse genereret ({len(tekst)} tegn)")
            return tekst
    except urllib.error.HTTPError as e:
        print(f"⚠️  API fejl {e.code}: {e.read().decode('utf-8')[:200]}")
        return None
    except Exception as e:
        print(f"⚠️  AI-analyse fejlede: {e}")
        return None


# ==========================================
# OFFENTLIGE FUNKTIONER
# ==========================================

def get_alarm_analyse(portfolio, latest_map, hits_data, hwm_data,
                      trail_alerts=None, momentum_svækkes=None,
                      corr_pairs=None, heatmap_data=None):
    """
    Genererer AI-tekst til alarm-mailen.
    Returnerer HTML-streng klar til indsætning, eller tom streng ved fejl.
    """
    payload = build_payload(
        portfolio, latest_map, hits_data, hwm_data,
        trail_alerts=trail_alerts,
        momentum_svækkes=momentum_svækkes,
        corr_pairs=corr_pairs,
        heatmap_data=heatmap_data,
    )
    tekst = call_claude(SYSTEM_ALARM, USER_ALARM.format(
        payload=json.dumps(payload, ensure_ascii=False, indent=2)
    ))
    if not tekst:
        return ""
    return _wrap_html(tekst, mode="alarm")


def get_weekly_analyse(portfolio, latest_map, hits_data, hwm_data,
                       corr_pairs=None, heatmap_data=None):
    """
    Genererer AI-tekst til ETF Weekly rapporten.
    Returnerer HTML-streng klar til indsætning, eller tom streng ved fejl.
    """
    payload = build_payload(
        portfolio, latest_map, hits_data, hwm_data,
        corr_pairs=corr_pairs,
        heatmap_data=heatmap_data,
    )
    tekst = call_claude(SYSTEM_WEEKLY, USER_WEEKLY.format(
        payload=json.dumps(payload, ensure_ascii=False, indent=2)
    ))
    if not tekst:
        return ""
    return _wrap_html(tekst, mode="weekly")


# ==========================================
# HTML-WRAPPER
# ==========================================

def _wrap_html(tekst, mode="weekly"):
    """Wrapper tekst i pæn HTML-boks klar til indsætning."""
    if mode == "alarm":
        return f"""
<div style="margin-bottom:20px; padding:14px 18px; background:#f0f4ff;
            border-left:4px solid #3b5bdb; border-radius:6px; font-size:14px; line-height:1.6;">
  <div style="font-weight:600; color:#3b5bdb; margin-bottom:6px;">🤖 AI-analyse</div>
  <div style="color:#333;">{tekst}</div>
</div>"""
    else:
        return f"""
<div class="ai-analyse">
  <div class="ai-analyse-header">🤖 AI-analyse</div>
  <div class="ai-analyse-tekst">{tekst}</div>
</div>"""
