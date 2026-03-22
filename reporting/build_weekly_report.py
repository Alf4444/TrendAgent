import json
import os
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION AF STIER
# ==========================================
# Vi finder rodmappen for projektet ud fra denne fils placering
BASE_DIR = Path(__file__).resolve().parents[1]

HISTORY_FILE_PATH = BASE_DIR / "data/history.json"
PORTFOLIO_FILE_PATH = BASE_DIR / "config/portfolio.json"
TEMPLATE_FILE_PATH = BASE_DIR / "templates/weekly.html.j2"
REPORT_OUTPUT_PATH = BASE_DIR / "build/weekly.html"

# ==========================================
# HJÆLPEFUNKTIONER (ROBUSTE)
# ==========================================

def beregn_sikker_division(tæller, nævner):
    """Sikrer at vi aldrig dividerer med nul."""
    if nævner == 0 or nævner is None:
        return 0.0
    return tæller / nævner

def beregn_afkast_procent(nuværende, tidligere):
    """Beregner procentvis ændring med sikkerhedstjek."""
    if tidligere is None or tidligere <= 0:
        return 0.0
    forskel = nuværende - tidligere
    resultat = (forskel / tidligere) * 100
    return resultat

def hent_ma_gennemsnit(pris_liste, periode):
    """Beregner gennemsnit for de sidste X dage."""
    if len(pris_liste) < periode:
        return None
    udsnit = pris_liste[-periode:]
    gennemsnit = sum(udsnit) / len(udsnit)
    return gennemsnit

# ==========================================
# HOVEDFUNKTION
# ==========================================

def build_weekly():
    # 1. Validering af at alle filer eksisterer før vi starter
    if not HISTORY_FILE_PATH.exists():
        print(f"FEJL: Historik-fil mangler på {HISTORY_FILE_PATH}")
        return
    if not PORTFOLIO_FILE_PATH.exists():
        print(f"FEJL: Portfolio-fil mangler på {PORTFOLIO_FILE_PATH}")
        return
    if not TEMPLATE_FILE_PATH.exists():
        print(f"FEJL: Template-fil mangler på {TEMPLATE_FILE_PATH}")
        return

    # 2. Indlæsning af data
    with open(HISTORY_FILE_PATH, "r", encoding="utf-8") as f:
        alle_historik_data = json.load(f)
    with open(PORTFOLIO_FILE_PATH, "r", encoding="utf-8") as f:
        portfolio_indstillinger = json.load(f)

    resultat_liste = []
    aktive_afkast_til_gennemsnit = []

    # 3. Behandling af hver enkelt fond
    for isin, historiske_kurser in alle_historik_data.items():
        # Sorter datoer kronologisk
        sorterede_datoer = sorted(historiske_kurser.keys())
        
        # Rens priser (fjern None, 0 og ugyldige typer)
        rensede_priser = []
        for dato in sorterede_datoer:
            pris = historiske_kurser[dato]
            if isinstance(pris, (int, float)) and pris > 0:
                rensede_priser.append(pris)
        
        # Vi skal bruge mindst 2 priser for at kunne sammenligne
        if len(rensede_priser) < 2:
            continue

        nuværende_nav = rensede_priser[-1]
        antal_datapunkter = len(rensede_priser)
        
        # Find historiske priser (uge = 6 handelsdage, måned = 21 handelsdage)
        pris_uge_siden = rensede_priser[-min(6, antal_datapunkter)]
        pris_måned_siden = rensede_priser[-min(21, antal_datapunkter)]

        # Beregn statistikker
        uge_afkast = beregn_afkast_procent(nuværende_nav, pris_uge_siden)
        måned_afkast = beregn_afkast_procent(nuværende_nav, pris_måned_siden)
        momentum_score = uge_afkast - måned_afkast

        # Glidende gennemsnit (MA)
        ma20_værdi = hent_ma_gennemsnit(rensede_priser, 20)
        ma20_afstand = 0.0
        if ma20_værdi is not None and ma20_værdi > 0:
            ma20_afstand = ((nuværende_nav - ma20_værdi) / ma20_værdi) * 100

        ma200_værdi = hent_ma_gennemsnit(rensede_priser, 200)
        trend_status = "WARM-UP"
        if ma200_værdi is not None:
            if nuværende_nav > ma200_værdi:
                trend_status = "BULL"
            else:
                trend_status = "BEAR"

        # Hent info fra portfolio.json
        fond_info = portfolio_indstillinger.get(isin, {})
        er_aktiv = fond_info.get('active', False)
        købspris = fond_info.get('buy_price', 0)
        
        total_afkast = None
        if er_aktiv and købspris is not None and købspris > 0:
            total_afkast = beregn_afkast_procent(nuværende_nav, købspris)
            aktive_afkast_til_gennemsnit.append(total_afkast)

        # Gem data for rækken
        resultat_liste.append({
            'isin': isin,
            'name': fond_info.get('name', isin),
            'nav': round(nuværende_nav, 2),
            'week_change_pct': round(uge_afkast, 2),
            'momentum': round(momentum_score, 2),
            'is_active': er_aktiv,
            'total_return': round(total_afkast, 2) if total_afkast is not None else None,
            't_state': trend_status,
            'ma20_dist': round(ma20_afstand, 2)
        })

    # 4. Beregn samlet porteføljeafkast
    samlet_gennemsnit = 0.0
    if len(aktive_afkast_til_gennemsnit) > 0:
        samlet_gennemsnit = sum(aktive_afkast_til_gennemsnit) / len(aktive_afkast_til_gennemsnit)

    # 5. Forbered data til graferne (Top 10 Momentum)
    top_10_momentum = sorted(resultat_liste, key=lambda x: x['momentum'], reverse=True)[:10]
    
    # SIKKERHED: Find den største momentum værdi til skalering i HTML
    # Dette sikrer at vi ikke dividerer med 0 inde i selve templaten
    max_skala_værdi = 1.0
    for r in resultat_liste:
        if abs(r['momentum']) > max_skala_værdi:
            max_skala_værdi = abs(r['momentum'])

    # 6. Rendering af HTML via Jinja2
    raw_template_text = TEMPLATE_FILE_PATH.read_text(encoding="utf-8")
    jinja_template = Template(raw_template_text)
    
    færdig_html = jinja_template.render(
        report_date=datetime.now().strftime("%d-%m-%Y"),
        week_number=datetime.now().isocalendar()[1],
        avg_portfolio_return=round(samlet_gennemsnit, 2),
        rows=resultat_liste,
        # Her sender vi de sorterede lister og sikkerhedsvariabler til templaten
        chart_labels=[r['name'][:15] for r in top_10_momentum],
        chart_values=[r['momentum'] for r in top_10_momentum],
        max_momentum=max_skala_værdi, # Bruges til at undgå division med 0 i HTML
        portfolio_alerts=[r for r in resultat_liste if r['is_active'] and r['week_change_pct'] < -3.0],
        market_opportunities=[r for r in resultat_liste if not r['is_active'] and r['momentum'] > 2.0 and r['t_state'] == "BULL"][:8]
    )

    # 7. Skriv den færdige rapport til fil
    REPORT_OUTPUT_PATH.parent.mkdir(exist_ok=True)
    REPORT_OUTPUT_PATH.write_text(færdig_html, encoding="utf-8")
    
    print(f"✅ Build gennemført succesfuldt. Rapport gemt i {REPORT_OUTPUT_PATH}")

if __name__ == "__main__":
    build_weekly()
