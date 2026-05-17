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


# ============================================================
# KORRELATIONSBEREGNING
# ============================================================

def _daily_returns(isin, history, days=90):
    """Beregner daglige afkast i % for de seneste 'days' handelsdage."""
    prices = history.get(isin, {})
    dates  = sorted(prices.keys())[-days-1:]
    vals   = [prices[d] for d in dates]
    if len(vals) < 2:
        return []
    return [(vals[i] - vals[i-1]) / vals[i-1] * 100 for i in range(1, len(vals))]


def _pearson(a, b):
    """Beregner Pearson korrelationskoefficient. Returnerer None hvis ikke nok data."""
    n = min(len(a), len(b))
    if n < 20:
        return None
    a, b   = a[-n:], b[-n:]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num    = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    den_a  = sum((x - mean_a) ** 2 for x in a) ** 0.5
    den_b  = sum((x - mean_b) ** 2 for x in b) ** 0.5
    if den_a == 0 or den_b == 0:
        return None
    return round(num / (den_a * den_b), 2)


def _corr_label(corr):
    """Returnerer (periode_tekst, vurdering_tekst, css_klasse) ud fra korrelationstal."""
    if corr is None:
        return "Ikke nok data", "— Ukendt", "corr-unknown"
    if corr > 0.85:
        return "Bevæger sig næsten identisk", "Ingen reel spredning", "corr-none"
    if corr > 0.70:
        return "Falder ofte sammen", "Begrænset spredning", "corr-low"
    if corr > 0.50:
        return "Falder af og til sammen", "Nogen spredning", "corr-ok"
    return "Bevæger sig uafhængigt", "God spredning", "corr-good"


def build_correlation_table(portfolio, history, days=90):
    """
    Beregner korrelation mellem alle par af aktive positioner.

    Returnerer:
      - pairs: liste af dicts klar til Jinja2-template
      - summary: opsummeringstekst til visning under tabellen
    """
    aktive = [
        (isin, info)
        for isin, info in portfolio.items()
        if info.get('active', False)
    ]

    if len(aktive) < 2:
        return [], ""

    returns = {
        isin: _daily_returns(isin, history, days)
        for isin, _ in aktive
    }

    pairs = []
    for i in range(len(aktive)):
        for j in range(i + 1, len(aktive)):
            isin_a, info_a = aktive[i]
            isin_b, info_b = aktive[j]
            corr           = _pearson(returns[isin_a], returns[isin_b])
            periode, vurdering, css = _corr_label(corr)
            pairs.append({
                "navn_a":    info_a.get('name', isin_a),
                "ticker_a":  info_a.get('ticker', ''),
                "navn_b":    info_b.get('name', isin_b),
                "ticker_b":  info_b.get('ticker', ''),
                "korr":      corr,
                "korr_str":  f"{corr:.2f}" if corr is not None else "—",
                "periode":   periode,
                "vurdering": vurdering,
                "css":       css,
                "advarsel":  corr is not None and corr > 0.70,
            })

    # Sortér: højest korrelation øverst
    pairs.sort(key=lambda x: -(x['korr'] or 0))

    # Byg opsummeringstekst
    ingen_spredning   = [p for p in pairs if p['css'] == 'corr-none']
    begraenset        = [p for p in pairs if p['css'] == 'corr-low']

    if ingen_spredning:
        navne = " og ".join(
            f"{p['ticker_a']} + {p['ticker_b']}" for p in ingen_spredning
        )
        summary = (
            f"{len(ingen_spredning)} par har ingen reel spredning ({navne}) — "
            f"de bevæger sig næsten identisk. Overvej om du reelt har "
            f"{'én position i stedet for to' if len(ingen_spredning) == 1 else 'færre positioner end du tror'}."
        )
    elif begraenset:
        navne = " og ".join(
            f"{p['ticker_a']} + {p['ticker_b']}" for p in begraenset
        )
        summary = (
            f"{len(begraenset)} par har begrænset spredning ({navne}) — "
            f"de falder ofte sammen i urolige markeder."
        )
    else:
        summary = (
            "God spredning på tværs af alle positioner — "
            "ingen par bevæger sig konsistent sammen."
        )

    return pairs, summary


def build_portfolio_correlation(isin_candidate, history, portfolio, days=90):
    """
    Beregner en kandidat-fonds gennemsnitlige korrelation mod porteføljen.
    Bruges af etf_spejder.py til at vise spredningsindikator på Spejder-kort.

    Returnerer: (korrelation_float_eller_None, label_str, css_str)
    """
    aktive_isins = [
        isin for isin, info in portfolio.items()
        if info.get('active', False) and isin != isin_candidate
    ]

    if not aktive_isins:
        return None, "—", "corr-unknown"

    cand_returns = _daily_returns(isin_candidate, history, days)
    if not cand_returns:
        return None, "—", "corr-unknown"

    korrelationer = []
    for isin in aktive_isins:
        port_returns = _daily_returns(isin, history, days)
        corr         = _pearson(cand_returns, port_returns)
        if corr is not None:
            korrelationer.append(corr)

    if not korrelationer:
        return None, "—", "corr-unknown"

    avg_corr = round(sum(korrelationer) / len(korrelationer), 2)
    _, vurdering, css = _corr_label(avg_corr)
    return avg_corr, vurdering, css
