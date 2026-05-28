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
    # Hvis rows er tilgængelige (fra build_weekly) bruges de direkte — de har alle beregnede værdier
    positioner = []
    rows = latest_map.get('__rows__', []) if isinstance(latest_map, dict) else []
    aktive_rows = [r for r in rows if r.get('is_active')]

    if aktive_rows:
        # Brug rows direkte — har total_return, momentum, rsi, trail_alert osv.
        for r in aktive_rows:
            hwm     = hwm_data.get(r.get('isin', ''), {})
            hwm_val = hwm.get('hwm', 0)
            curr    = r.get('curr_price', 0)
            hwm_afstand = round(((curr / hwm_val) - 1) * 100, 1) if hwm_val and curr else None
            positioner.append({
                'ticker':      r.get('ticker', ''),
                'navn':        r.get('name', ''),
                'sektor':      r.get('category', '—'),
                'depot':       r.get('depot', '—'),
                'afkast_pct':  r.get('total_return'),
                'momentum':    r.get('momentum'),
                'rsi':         r.get('rsi'),
                'trail_alert': bool(r.get('trail_alert')),
                'hwm_afstand': hwm_afstand,
                'ask_egnet':   r.get('ask_eligible', False),
            })
    else:
        # Fallback: byg fra portfolio + latest_map
        for isin, p in portfolio.items():
            if not p.get('active', False):
                continue
            latest_item = latest_map.get(isin, {}) if isinstance(latest_map, dict) else {}
            hwm         = hwm_data.get(isin, {})
            buy         = p.get('buy_price', 0)
            curr        = latest_item.get('nav', 0)
            afkast      = round(((curr / buy) - 1) * 100, 1) if buy and curr else None
            hwm_val     = hwm.get('hwm', 0)
            hwm_afstand = round(((curr / hwm_val) - 1) * 100, 1) if hwm_val and curr else None
            positioner.append({
                'ticker':      p.get('ticker', isin),
                'navn':        p.get('name', isin),
                'sektor':      latest_item.get('category', p.get('category', '—')),
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
        try:
            sektorer = {}
            # build_heatmap() returnerer liste med {kategori, andel_pct, antal, fonde}
            if isinstance(heatmap_data, list):
                for item in heatmap_data:
                    kat = item.get('kategori', '')
                    pct = item.get('andel_pct', 0)
                    if kat and pct:
                        sektorer[kat] = pct
            elif isinstance(heatmap_data, dict):
                for kat, data in heatmap_data.items():
                    if isinstance(data, dict) and data.get('andel_pct'):
                        sektorer[kat] = data['andel_pct']
            if sektorer:
                risiko['sektor_fordeling'] = sektorer
        except Exception as e:
            print(f"⚠️  Heatmap-data kunne ikke læses: {e}")

    if corr_pairs:
        # build_correlation_table() returnerer pairs med {ticker_a, ticker_b, korr, css}
        høj_korr = [
            f"{p.get('ticker_a','')}/{p.get('ticker_b','')}: {p.get('korr','')}"
            for p in corr_pairs
            if isinstance(p.get('korr'), float) and p['korr'] >= 0.85
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
Du modtager porteføljedata og aktuelle signaler i JSON og skriver en kort analyse på dansk.

Tone skalerer med signalernes alvorlighed:
- Kun nye kandidater: rolig og informerende
- K1: opmærksom, fx "hold ekstra øje med X de næste dage"
- K2: tydelig, fx "styrken i X er næsten væk — rotation bør overvejes"
- K3 eller Trail Stop: direkte, fx "to signaler på X — handling er relevant"

Regler:
- Skriv kun dansk, ingen markdown, ingen bullet points, ingen linjeskift midt i teksten
- Brug altid de konkrete ticker-navne (fx VVSM.DE) når du nævner fonde
- Nævn altid hvilken fond signalet handler om og hvad det konkret betyder
- Hvis der er ASK-egnede kandidater der passer til rotation, nævn den bedste specifikt
- Max 4-5 sætninger i sammenhængende tekst
- Undgå finansiel rådgivning — beskriv hvad dataene viser"""

SYSTEM_WEEKLY = """Du er en kortfattet, dansk porteføljeassistent for en privat investor.
Du modtager porteføljedata i JSON og skriver et ugentligt overblik på dansk.

Tone: rolig, analytisk — som en ugentlig status til sig selv.

Regler:
- Skriv kun dansk, ingen markdown, ingen bullet points, ingen linjeskift midt i teksten
- Brug altid de konkrete ticker-navne (fx VVSM.DE, FLXK.DE) når du nævner fonde
- Start med samlet porteføljestatus: antal positioner, depottyper
- Nævn de stærkeste og svageste positioner med afkast-tal
- Nævn koncentrationsrisiko konkret hvis en sektor er over 40% (fx "Halvledere fylder 50%")
- Nævn høj korrelation hvis to fonde bevæger sig identisk (korr > 0.85)
- Afslut med de 1-2 bedste ASK-egnede kandidater til rotation hvis relevant
- Max 5-6 sætninger i sammenhængende tekst
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
                       corr_pairs=None, heatmap_data=None, rows=None):
    """
    Genererer AI-tekst til ETF Weekly rapporten.
    Returnerer HTML-streng klar til indsætning, eller tom streng ved fejl.
    """
    # Injicer rows i latest_map så build_payload kan bruge dem
    if rows is not None:
        latest_map = dict(latest_map) if latest_map else {}
        latest_map['__rows__'] = rows

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
# LAG 3 — HÆNDELSESDREVET ANALYSE
# ==========================================

# Anti-spam for Lag 3 — gemmer hvornår en fond sidst blev analyseret
# Format: {isin: {kriterium: dato}}
_LAG3_CACHE = {}

SYSTEM_LAG3 = """Du er en kortfattet, dansk porteføljeassistent for en privat investor.
Du modtager nyheder om en specifik fond og dens sektor efter et signal om svækkelse.
Skriv 2-3 sætninger på dansk der forklarer hvad der driver bevægelsen og om det er midlertidigt eller strukturelt.

Regler:
- Skriv kun dansk, ingen markdown, ingen bullet points
- Brug fondens ticker-navn (fx HYCN.DE)
- Vær konkret — hvad siger kilderne præcist?
- Afslut med én sætning: midlertidigt eller strukturelt?
- Max 3 sætninger
- Undgå finansiel rådgivning"""

USER_LAG3 = """Signal: {kriterium} på {ticker} ({navn})

Markedsnyheder:
{news}

Skriv en kort kontekst-analyse til alarm-mailen. Er dette midlertidigt eller strukturelt?"""


def get_signal_analyse(ticker, navn, sektor, kriterium, api_key=None):
    """
    Lag 3: Hændelsesdrevet analyse for ét signal.
    Laver 2 søgninger og skriver 2-3 sætninger om årsag + midlertidigt/strukturelt.

    Returnerer HTML-streng eller tom streng ved fejl/anti-spam.
    Anti-spam: samme fond + kriterium analyseres ikke igen inden for 3 dage.
    """
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return ""

    # Anti-spam check
    import datetime
    today = datetime.date.today().isoformat()
    cache_key = f"{ticker}_{kriterium}"
    if _LAG3_CACHE.get(cache_key) == today:
        print(f"   ⏭️  Lag 3 anti-spam: {ticker} {kriterium} allerede analyseret i dag")
        return ""

    print(f"   🔍 Lag 3: søger på {ticker} ({kriterium})...")

    # Søgning 1: fond-specifikke nyheder
    q1 = f"{navn} ETF news"
    # Søgning 2: sektor-outlook
    q2 = f"{sektor} outlook 2026" if sektor and sektor != "—" else f"{ticker} sector outlook"

    news_parts = []
    for label, query in [(ticker, q1), (sektor, q2)]:
        result = _web_search_via_claude(query, api_key)
        if result:
            nl = "\n"
            news_parts.append(f"{label}:{nl}{result}")
            print(f"   ✅ Lag 3 søgning '{label}': {len(result)} tegn")
        time.sleep(5)

    if not news_parts:
        print(f"   ⚠️  Lag 3: ingen søgeresultater for {ticker}")
        return ""

    # Vent så token-vinduet ikke overskrides
    print(f"   ⏳ Lag 3: venter 30 sek inden skriv-kald...")
    time.sleep(30)

    nl = "\n\n"
    news_tekst = nl.join(news_parts)
    user_prompt = USER_LAG3.format(
        kriterium=kriterium,
        ticker=ticker,
        navn=navn,
        news=news_tekst,
    )

    tekst = call_claude(SYSTEM_LAG3, user_prompt)
    if not tekst:
        return ""

    # Opdater anti-spam cache
    _LAG3_CACHE[cache_key] = today
    print(f"   ✅ Lag 3 analyse: {ticker} ({len(tekst)} tegn)")

    return f"""<div style="margin-top:8px; padding:8px 12px; background:#f0f4ff;
                border-left:3px solid #3b5bdb; border-radius:0 4px 4px 0;
                font-size:12px; color:#333; line-height:1.5;">
      <span style="font-weight:600; color:#3b5bdb;">🤖 AI-kontekst:</span> {tekst}
    </div>"""


def get_all_signal_analyser(signaler, watchlist=None):
    """
    Kører Lag 3 for en liste af signaler.
    Prioriterer Trail Stop > K3 > K2. Max 2 signaler per kørsel.

    signaler: liste af dicts med {ticker, navn, sektor, kriterium}
    Returnerer: dict {ticker: html_tekst}
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return {}

    # Sorter efter prioritet
    prioritet = {"Trail Stop": 0, "K3": 1, "K2": 2, "K1": 9}
    sorterede = sorted(signaler, key=lambda x: prioritet.get(x.get("kriterium", "K1"), 9))

    # Max 2 signaler — spring K1 over
    kandidater = [s for s in sorterede if s.get("kriterium") != "K1"][:2]

    if not kandidater:
        return {}

    print(f"   📰 Lag 3: analyserer {len(kandidater)} signal(er)...")
    # Vent så Lag 1 tokens er clearet
    time.sleep(30)

    resultater = {}
    for s in kandidater:
        ticker   = s.get("ticker", "")
        navn     = s.get("navn", ticker)
        sektor   = s.get("sektor", "—")
        kriterium = s.get("kriterium", "")
        html = get_signal_analyse(ticker, navn, sektor, kriterium, api_key)
        if html:
            resultater[ticker] = html

    return resultater


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
