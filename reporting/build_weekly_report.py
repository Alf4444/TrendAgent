import json
import os
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION & STIER
# ==========================================
# Vi definerer stierne helt eksplicit så de virker på GitHub
BASE_DIR = Path(__file__).resolve().parents[1]
HISTORY_PATH = BASE_DIR / "data/history.json"
PORTFOLIO_PATH = BASE_DIR / "config/portfolio.json"
TEMPLATE_PATH = BASE_DIR / "templates/weekly.html.j2"
REPORT_OUTPUT_PATH = BASE_DIR / "build/weekly.html"

def beregn_ma_kurs(priser, vindue):
    """Beregner simpelt glidende gennemsnit (MA)."""
    if not priser or len(priser) < vindue:
        return None
    
    valgte_priser = priser[-vindue:]
    summen = sum(valgte_priser)
    antal = len(valgte_priser)
    
    if antal > 0:
        return summen / antal
    return None

def build_weekly():
    # 1. Tjek om nødvendige filer findes
    if not HISTORY_PATH.exists():
        print(f"FEJL: Historik-fil ikke fundet på {HISTORY_PATH}")
        return
    if not PORTFOLIO_PATH.exists():
        print(f"FEJL: Portfolio-fil ikke fundet på {PORTFOLIO_PATH}")
        return

    # 2. Indlæs data
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        historik_data = json.load(f)
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        portfolio_config = json.load(f)

    rækker_til_rapport = []
    aktive_afkast_liste = []
    
    # 3. Gennemgå hver fond (ISIN)
    for isin, dato_priser in historik_data.items():
        # Sorter datoer og hent priser (rens for 0 og None)
        sorterede_datoer = sorted(dato_priser.keys())
        rensede_priser = []
        for dato in sorterede_datoer:
            pris = dato_priser[dato]
            if pris is not None and isinstance(pris, (int, float)) and pris > 0:
                rensede_priser.append(pris)
        
        # Vi skal bruge mindst 2 priser for at beregne ændring
        if len(rensede_priser) < 2:
            continue
            
        nuværende_kurs = rensede_priser[-1]
        
        # Hent priser for uge (6 dage) og måned (21 dage)
        antal_priser = len(rensede_priser)
        kurs_sidste_uge = rensede_priser[-min(6, antal_priser)]
        kurs_sidste_måned = rensede_priser[-min(21, antal_priser)]
        
        # --- BEREGNING AF AFKAST (Sikret mod division med nul) ---
        uge_afkast = 0.0
        if kurs_sidste_uge > 0:
            uge_afkast = ((nuværende_kurs - kurs_sidste_uge) / kurs_sidste_uge) * 100
            
        måned_afkast = 0.0
        if kurs_sidste_måned > 0:
            måned_afkast = ((nuværende_kurs - kurs_sidste_måned) / kurs_sidste_måned) * 100
            
        momentum_score = uge_afkast - måned_afkast
        
        # --- TEKNISK ANALYSE (MA) ---
        ma20_værdi = beregn_ma_kurs(rensede_priser, 20)
        ma20_afstand = 0.0
        if ma20_værdi is not None and ma20_værdi > 0:
            ma20_afstand = ((nuværende_kurs - ma20_værdi) / ma20_værdi) * 100
            
        ma200_værdi = beregn_ma_kurs(rensede_priser, 200)
        marked_status = "AFVENTER"
        if ma200_værdi is not None:
            if nuværende_kurs > ma200_værdi:
                marked_status = "BULL"
            else:
                marked_status = "BEAR"

        # --- PORTFOLIO INFO ---
        fond_info = portfolio_config.get(isin, {})
        er_aktiv = fond_info.get('active', False)
        købspris = fond_info.get('buy_price', 0)
        
        total_afkast = None
        if er_aktiv and købspris is not None and købspris > 0:
            total_afkast = ((nuværende_kurs - købspris) / købspris) * 100
            aktive_afkast_liste.append(total_afkast)

        # Tilføj data til listen
        rækker_til_rapport.append({
            'isin': isin,
            'name': fond_info.get('name', isin),
            'nav': round(nuværende_kurs, 2),
            'week_change_pct': round(uge_afkast, 2),
            'momentum': round(momentum_score, 2),
            'is_active': er_aktiv,
            'total_return': round(total_afkast, 2) if total_afkast is not None else None,
            't_state': marked_status,
            'ma20_dist': round(ma20_afstand, 2)
        })

    # 4. Beregn gennemsnit for porteføljen
    portefølje_gennemsnit = 0.0
    if len(aktive_afkast_liste) > 0:
        portefølje_gennemsnit = sum(aktive_afkast_liste) / len(aktive_afkast_liste)

    # 5. Forbered data til grafer (Top 10 Momentum)
    # Vi sikrer at vi ikke fejler hvis listen er kort
    sorteret_efter_momentum = sorted(rækker_til_rapport, key=lambda x: x['momentum'], reverse=True)
    top_10_fonde = sorteret_efter_momentum[:10]
    
    graf_navne = []
    graf_værdier = []
    for f in top_10_fonde:
        graf_navne.append(f['name'][:15]) # Afkort navn til graf
        graf_værdier.append(f['momentum'])

    # 6. Generer HTML rapporten via Jinja2
    if not TEMPLATE_PATH.exists():
        print(f"FEJL: HTML template ikke fundet på {TEMPLATE_PATH}")
        return

    skabelon_tekst = TEMPLATE_PATH.read_text(encoding="utf-8")
    jinja_template = Template(skabelon_tekst)
    
    html_indhold = jinja_template.render(
        report_date=datetime.now().strftime("%d-%m-%Y"),
        week_number=datetime.now().isocalendar()[1],
        avg_portfolio_return=round(portefølje_gennemsnit, 2),
        rows=rækker_til_rapport,
        chart_labels=graf_navne,
        chart_values=graf_værdier
    )

    # 7. Gem den færdige fil
    REPORT_OUTPUT_PATH.parent.mkdir(exist_ok=True)
    REPORT_OUTPUT_PATH.write_text(html_indhold, encoding="utf-8")
    
    print(f"✅ Build gennemført succesfuldt. Rapport gemt i {REPORT_OUTPUT_PATH}")

if __name__ == "__main__":
    build_weekly()
