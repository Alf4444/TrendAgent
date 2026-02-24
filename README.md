# 🛡️ TrendAgent: Teknisk Manual & Systemdokumentation

Dette system er en automatiseret investeringsassistent, der overvåger trends og momentum i investeringsfonde ved hjælp af 200-dages glidende gennemsnit (MA200).

---

## 📅 Daily Engine: Dataindsamling (`daily.py`)

**Formål:** At fungere som systemets database-motor, der sikrer kontinuerlig historik og øjebliksbillede af markedet.

### Funktioner:
* **NAV Indhentning:** Henter dagens lukkekurs (Net Asset Value) for alle ISIN i porteføljen.
* **Historik-arkivering:** Gemmer data i `data/history.json`. Hver fond kræver >200 datapunkter for korrekt trend-analyse.
* **Snapshot:** Genererer `data/latest.json` med dagsaktuelle nøgletal.

### Kolonner i Daily View (TrendAgent Fokus):
| Kolonne | Beskrivelse |
| :--- | :--- |
| **Fond** | Navnet på fonden. Stjerne (⭐) markerer aktive porteføljevalg. |
| **Signal** | Viser handlinger: `🚀 KØB` ved BULL-skift eller `⚠️ SALG` ved BEAR-skift. |
| **Egen %** | Dit personlige afkast på positionen (hvis købskurs er angivet). |
| **Trend** | **BULL:** Pris > MA200. **BEAR:** Pris < MA200. |
| **Afstand** | Momentum. Hvor mange % fonden er over/under sin MA200-linje. |
| **1D %** | Kursændringen siden i går. Bruges til at spotte pludselige bevægelser. |
| **DD** | **Drawdown:** Det aktuelle fald fra fondens højeste historiske toppunkt. |

---

## 📈 Weekly Engine: Analyse & Dashboard (`build_weekly_report.py`)

**Formål:** At opsummere ugens bevægelser og identificere langsigtede trendskift.

### Funktioner & Sortering:
* **Trend-skift detektion:** Sammenligner mandagens trend med fredagens trend. Skift udløser en alarm øverst i rapporten.
* **Top/Bund Sortering:** Identificerer automatisk de 5 fonde med hhv. højeste og laveste afkast de sidste 7 dage.
* **Momentum Graf:** Viser visuelt styrken på dine egne fonde (⭐) for hurtig prioritering.

### Kolonner i Weekly Report:
* **Fond:** Navn (afkortet til 45 tegn for læsbarhed).
* **Uge %:** Fondens samlede afkast i den pågældende uge.
* **Trend:** Viser nuværende status (BULL/BEAR) baseret på ugens sidste lukkekurs.
* **Momentum:** Relativ afstand til MA200. Er hjørnestenen i strategien.
* **ÅTD (YTD):** Year-to-Date. Fondens afkast siden 1. januar i indeværende år.
* **Drawdown:** Risiko-indikator. Viser hvor tæt fonden er på sin "All-time High".

### Alarmer & Logik:
1. **Portefølje-alarmer (⭐):** Udløses ved ALLE trendskift for dine egne fonde.
2. **Markedsmuligheder (🎯):** Udløses kun når eksterne fonde skifter til BULL (Købssignal).
