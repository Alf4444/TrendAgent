# 🛡️ TrendAgent: Teknisk Manual & Systemdokumentation

Dette system er en automatiseret investeringsassistent, der overvåger trends og momentum i investeringsfonde ved hjælp af 200-dages glidende gennemsnit (MA200).

---

## 📅 Daily Engine: Dataindsamling (`daily.py`)

**Formål:** At fungere som systemets database-motor, der sikrer kontinuerlig historik og øjebliksbillede af markedet. Henter daglige kurser og udfører den primære tekniske beregning for hver fond.

### Funktioner:
* **NAV Indhentning:** Henter dagens lukkekurs (Net Asset Value) for alle ISIN i porteføljen.
* **Historik-arkivering:** Gemmer data i `data/history.json`. Hver fond kræver >200 datapunkter for korrekt trend-analyse.
* **Snapshot:** Genererer `data/latest.json` med dagsaktuelle nøgletal.

### Kolonner i Daily View (TrendAgent Fokus):
| Kolonne | Beskrivelse |
| Kolonne | Formål | Logik |
| **Fond** | Identifikation | Navn + ISIN (⭐ markerer egne positioner). |
| **Signal** | Viser handlinger: `🚀 KØB` ved BULL-skift (Pris bryder MA200 op) eller `⚠️ SALG` ved BEAR-skift (Pris bryder MA200 ned). |
| **Egen %** | Dit personlige afkast på positionen (hvis købskurs er angivet). |
| **Trend** | Overordnet filter | **BULL:** hvis Pris > MA200. **BEAR:** hvis Pris < MA200. |
| **Afstand** | Sikkerhedsmargin | Momentum. Hvor mange % fonden er over/under sin MA200-linje. |
| **1D %** | Kursændringen siden i går. Bruges til at spotte pludselige bevægelser. |
| **DD (Drawdown)**| Risikostyring | Procentvist fald fra fondens højeste registrerede kurs (Peak). |
| **Cross 20/50**| Tidlig indikator | Viser `GOLDEN`, hvis MA20 krydser MA50 opad (stærkt købssignal før MA200). |

---

## 📈 Weekly Engine: Analyse & Dashboard (`build_weekly_report.py`)

**Formål:** At opsummere ugens bevægelser og identificere langsigtede trendskift. Genererer et dashboard, der opsummerer ugens bevægelser og detekterer trendskift over en 7-dages periode.

### Funktioner & Sortering:
* **Trend-skift detektion:** Sammenligner mandagens trend med fredagens trend. Skift udløser en alarm øverst i rapporten.
* **MA-Hierarki:** Analyserer forholdet mellem MA20, MA50 og MA200 for at vurdere trendstyrke.
* **Top/Bund Sortering:** Identificerer automatisk de 5 fonde med hhv. højeste og laveste afkast de sidste 7 dage.
* **Momentum Graf:** Viser visuelt styrken på dine egne fonde (⭐) for hurtig prioritering.
* **Sortering:** Prioriterer dine egne fonde øverst, efterfulgt af markedets stærkeste momentum-kandidater.

### Kolonner i Weekly Report:
* **Fond:** Navn (afkortet til 45 tegn for læsbarhed).
* **Uge %:** Fondens samlede afkast i den pågældende uge.
* **Trend:** Viser nuværende status (BULL/BEAR) baseret på ugens sidste lukkekurs.
* **Momentum:** Relativ afstand til MA200. Er hjørnestenen i strategien. (bruges til at vælge de stærkeste fonde i et BULL-marked).
* **ÅTD (YTD):** Year-to-Date. Fondens afkast siden 1. januar i indeværende år.
* **Drawdown:** Risiko-indikator. Viser hvor tæt fonden er på sin "All-time High".

### Alarmer & Logik:
1. **Portefølje-alarmer (⭐):** Udløses ved ALLE trendskift for dine egne fonde.
2. **Markedsmuligheder (🎯):** Udløses kun når eksterne fonde skifter til BULL (Købssignal).
# 🛡️ TrendAgent: Teknisk Dokumentation & Strategi
