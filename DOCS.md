# 🛡️ DOCS: Teknisk Manual & Systemdokumentation

Denne fil indeholder den permanente dokumentation for TrendAgent-systemet. Systemet er designet til at fjerne følelser fra investering ved at bruge matematiske gennemsnit (20, 50, 200) til at diktere købs- og salgssignaler.

---

## 📅 Daily Engine: Overvågning (`reporting/build_daily.py`)

**Formål:** At fungere som systemets daglige kontrolcenter. Scriptet analyserer de nyeste data, opdaterer GitHub-forsiden (README.md) og genererer et visuelt dashboard (`daily.html`).

### Funktioner:
* **Trend-analyse:** Beregner om fonde er i BULL eller BEAR marked baseret på MA200.
* **Signal-generering:** Detekterer præcise kryds (🚀 KØB / ⚠️ SALG) i det øjeblik, prisen krydser MA200.
* **Intelligent Sortering:** Aktive fonde (⭐) vises altid øverst, efterfulgt af nye købssignaler og derefter markedets stærkeste momentum-fonde.
* **README Opdatering:** Overskriver automatisk forsiden på GitHub med den aktuelle status.

### Kolonner i Daily View (TrendAgent Fokus):

| Kolonne | Formål | Logik |
| :--- | :--- | :--- |
| **Fond** | Identifikation | Navn + ISIN (⭐ markerer egne positioner). |
| **Signal** | Handling | `🚀 KØB` (Pris bryder MA200 op), `⚠️ SALG` (Pris bryder MA200 ned). |
| **Egen %** | Performance | Dit afkast baseret på `buy_price` i `portfolio.json`. |
| **Trend** | Filter | **BULL:** Pris > MA200. **BEAR:** Pris < MA200. |
| **Afstand** | Momentum | Procentvis afstand fra nuværende kurs til MA200. |
| **Cross 20/50**| Tidligt varsel | Viser `GOLDEN`, hvis MA20 krydser over MA50 (Tidligt købssignal). |
| **1D %** | Volatilitet | Kursændringen siden sidste bankdag. |
| **DD (Drawdown)**| Risiko | Procentvist fald fra fondens højeste historiske kurs (Peak). |

---

## 📈 Weekly Engine: Analyse & Dashboard (`reporting/build_weekly_report.py`)

**Formål:** At give et strategisk overblik over ugens bevægelser og identificere langsigtede trendskift. Genererer det store ugentlige dashboard.

### Funktioner & Sortering:
* **Trend-skift detektion:** Sammenligner trend-status ved ugens start og slut. Skift udløser en alarm øverst i rapporten.
* **MA-Hierarki:** Analyserer forholdet mellem MA20, MA50 og MA200 for at vurdere trendens styrke.
* **Top/Bund Sortering:** Finder automatisk ugens 5 vindere og 5 tabere.
* **Momentum Graf:** Viser visuelt afstanden til MA200 for dine egne fonde (⭐).

### Kolonner i Weekly Report:
* **Fond:** Navnet på fonden (afkortet for bedre overblik).
* **Uge %:** Det samlede afkast over de sidste 7 dage.
* **Trend:** Den aktuelle status (BULL/BEAR).
* **Momentum:** Afstanden til MA200 – bruges til at finde de stærkeste fonde i et BULL-marked.
* **ÅTD (YTD):** Afkastet siden 1. januar.
* **Drawdown:** Hvor langt fonden er fra sin "All-time High".

### Alarmer & Logik:
1. **Portefølje-alarmer (⭐):** Udløses ved ALLE trendskift for dine egne fonde, da de kræver øjeblikkelig handling.
2. **Markedsmuligheder (🎯):** Udløses kun, når en fond, du ikke ejer, skifter til BULL (potentiel ny investering).

---

## 📂 Filstruktur & Dataflow
1. `data/history.json`: Den fulde pris-historik (kræver >200 dage for fuld analyse).
2. `data/latest.json`: Den nyeste kurs indhentet af dataindsamleren.
3. `config/portfolio.json`: Dine aktive fonde og købspriser.
4. `reporting/build_daily.py`: Opdaterer README og Daily HTML.
5. `reporting/build_weekly_report.py`: Genererer ugerapporten.

---
*Sidst opdateret: 24. februar 2026*
