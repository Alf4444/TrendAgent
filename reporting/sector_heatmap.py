"""
sector_heatmap.py
Beregner sektor/kategori-eksponering for PFA og ETF porteføljerne.
Returnerer data klar til Jinja2-template heatmap.
Bruges af pfa_build_monthly_report.py, etf_build_monthly.py,
         pfa_build_weekly_report.py og etf_build_weekly.py
"""


# ============================================================
# FARVER PR. KATEGORI-PRÆFIX
# Bruges i HTML-template til visuel farvekodning
# ============================================================

CATEGORY_COLORS = {
    "Region":   "#1a73e8",   # Blå
    "Sektor":   "#1e8e3e",   # Grøn
    "Tema":     "#f59c00",   # Guld
    "Råvarer":  "#8b4513",   # Brun
    "Lande":    "#7b1fa2",   # Lilla
    "Benchmark":"#888888",   # Grå
}

def _get_color(category):
    """Returnerer farve baseret på kategori-præfix."""
    if not category:
        return "#cccccc"
    prefix = category.split("—")[0].strip()
    return CATEGORY_COLORS.get(prefix, "#4ecdc4")


# ============================================================
# HOVED-BEREGNING
# ============================================================

def build_heatmap(portfolio, active_fund_data, watchlist=None):
    """
    Beregner sektor-eksponering for en portefølje.

    Args:
        portfolio: dict fra pfa_portfolio.json eller etf_portfolio.json
        active_fund_data: liste af fund_data dicts (fra build_monthly/weekly)
                          — bruges til at hente total_return pr. fond
        watchlist: dict fra etf_watchlist.json (til ETF-kategorier) eller None

    Returns:
        liste af dicts sorteret efter antal fonde, klar til template:
        [
          {
            "kategori": "Region — Emerging Markets",
            "farve": "#1a73e8",
            "fonde": [
              {
                "navn": "Lazard Emerging Markets Equity Fund",
                "isin": "PFA000002703",
                "ticker": None,
                "total_return": "+6.7%",
                "total_return_raw": 6.7,
                "andel_pct": 50.0,   # andel af aktive positioner
              }
            ],
            "antal": 2,
            "andel_pct": 50.0,   # samlet andel for kategorien
          }
        ]
    """
    # Byg lookup: isin → total_return fra aktive fund_data
    return_lookup = {}
    for f in active_fund_data:
        return_lookup[f['isin']] = f.get('total_return', 0)

    # Tæl kun aktive positioner
    aktive = {
        isin: info for isin, info in portfolio.items()
        if info.get('active', False)
    }
    total_aktive = len(aktive)
    if total_aktive == 0:
        return []

    # Grupér efter kategori
    kategorier = {}
    for isin, info in aktive.items():
        # Hent kategori — fra portfolio direkte, eller fra watchlist
        kategori = info.get('category', '')
        if not kategori and watchlist:
            kategori = watchlist.get(isin, {}).get('category', '')
        if not kategori:
            kategori = 'Uklassificeret'

        ticker       = info.get('ticker') or None
        total_return = return_lookup.get(isin, 0)
        tr_fmt       = f"{'+' if total_return >= 0 else ''}{total_return:.1f}%"

        fond = {
            "navn":             info.get('name', isin),
            "isin":             isin,
            "ticker":           ticker,
            "total_return":     tr_fmt,
            "total_return_raw": total_return,
            "positiv":          total_return >= 0,
        }

        if kategori not in kategorier:
            kategorier[kategori] = []
        kategorier[kategori].append(fond)

    # Byg resultat-liste med andele
    resultat = []
    for kat, fonde in kategorier.items():
        andel = round(len(fonde) / total_aktive * 100)
        resultat.append({
            "kategori":  kat,
            "farve":     _get_color(kat),
            "fonde":     fonde,
            "antal":     len(fonde),
            "andel_pct": andel,
        })

    # Sortér: flest fonde øverst, dernæst alfabetisk
    return sorted(resultat, key=lambda x: (-x['antal'], x['kategori']))


# ============================================================
# KONCENTRATIONS-ADVARSEL
# ============================================================

def get_concentration_warning(heatmap):
    """
    Returnerer en advarsel hvis én kategori udgør mere end 50% af porteføljen.
    Returnerer None hvis ingen koncentrations-risiko.
    """
    for kat in heatmap:
        if kat['andel_pct'] >= 50:
            return {
                "kategori":  kat['kategori'],
                "andel_pct": kat['andel_pct'],
                "antal":     kat['antal'],
            }
    return None


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import json

    pfa = json.load(open('/mnt/user-data/uploads/pfa_portfolio.json'))
    etf_p = json.load(open('/mnt/user-data/uploads/etf_portfolio.json'))
    wl  = json.load(open('/mnt/user-data/uploads/etf_watchlist.json'))

    # Simulér active_fund_data
    pfa_funds = [
        {"isin": "PFA000002703", "total_return": 6.7},
        {"isin": "PFA000002732", "total_return": 14.3},
        {"isin": "PFA000002726", "total_return": 9.8},
        {"isin": "PFA000002753", "total_return": 2.0},
    ]

    print("=== PFA HEATMAP ===")
    hm = build_heatmap(pfa, pfa_funds)
    for kat in hm:
        print(f"  {kat['kategori']} ({kat['andel_pct']}% — {kat['antal']} fonde):")
        for f in kat['fonde']:
            print(f"    - {f['navn']}: {f['total_return']}")

    warn = get_concentration_warning(hm)
    if warn:
        print(f"\n  ⚠️  KONCENTRATION: {warn['kategori']} = {warn['andel_pct']}%")

    etf_funds = [
        {"isin": "IE00BMC38736", "total_return": 9.2},
        {"isin": "IE00BHZRR030", "total_return": 11.4},
    ]

    print("\n=== ETF HEATMAP ===")
    hm_etf = build_heatmap(etf_p, etf_funds, watchlist=wl)
    for kat in hm_etf:
        print(f"  {kat['kategori']} ({kat['andel_pct']}% — {kat['antal']} fonde):")
        for f in kat['fonde']:
            print(f"    - {f['navn']} ({f['ticker']}): {f['total_return']}")
