"""
validate_data.py — Automatisk datakontrol for TrendAgent
=========================================================
Køres af main.py efter daglig dataopdatering.
Tjekker latest.json og history.json for fejl og uoverensstemmelser.

Returnerer antal kritiske fejl (exit code 0 = OK, >0 = fejl fundet).
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT           = Path(__file__).resolve().parents[1]

# PFA filer
LATEST_FILE    = ROOT / "data/latest.json"
HISTORY_FILE   = ROOT / "data/history.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"

# ETF filer
ETF_LATEST_FILE    = ROOT / "data/etf_latest.json"
ETF_HISTORY_FILE   = ROOT / "data/etf_history.json"
ETF_PORTFOLIO_FILE = ROOT / "config/etf_portfolio.json"
ETF_WATCHLIST_FILE = ROOT / "config/etf_watchlist.json"

# Grænser — PFA
NAV_JUMP_PCT        = 0.15   # Max dagligt kursspring PFA (15%)
RETURN_SANITY_MAX   = 200.0  # Max afkastprocent der giver mening (200%)
RETURN_SANITY_MIN   = -80.0  # Min afkastprocent der giver mening (-80%)
MIN_HISTORY_POINTS  = 5      # Min datapunkter i historik

# Grænser — ETF (løsere da ETF'er er mere volatile)
ETF_NAV_JUMP_PCT    = 0.25   # Max dagligt kursspring ETF (25%)
ETF_MAX_DATA_AGE    = 5      # Max dage gammel data før fejl


def load_json(path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return None


def validate(verbose=True):
    """
    Kører alle valideringstjek.
    Returnerer (kritiske_fejl, advarsler) som to lister af strings.
    """
    errors   = []  # Kritiske fejl — kræver handling
    warnings = []  # Advarsler — bør undersøges

    # ==========================================
    # INDLÆS DATA
    # ==========================================
    latest    = load_json(LATEST_FILE)
    history   = load_json(HISTORY_FILE)
    portfolio = load_json(PORTFOLIO_FILE)

    if latest is None:
        errors.append(f"KRITISK: {LATEST_FILE} mangler eller kan ikke læses")
        return errors, warnings
    if history is None:
        errors.append(f"KRITISK: {HISTORY_FILE} mangler eller kan ikke læses")
        return errors, warnings
    if portfolio is None:
        warnings.append(f"ADVARSEL: {PORTFOLIO_FILE} mangler — porteføljevalidering springes over")

    latest_map = {item['isin']: item for item in latest if 'isin' in item}
    today      = datetime.now().strftime('%Y-%m-%d')

    # ==========================================
    # TJEK 1: latest.json — grundlæggende felter
    # ==========================================
    for item in latest:
        isin = item.get('isin', '?')
        name = item.get('name', isin)[:35]

        # NAV skal være til stede og positiv
        if not item.get('nav') or item['nav'] <= 0:
            errors.append(f"FEJL: {isin} ({name}) mangler NAV")

        # Dato skal være til stede
        if not item.get('nav_date'):
            errors.append(f"FEJL: {isin} ({name}) mangler nav_date")

        # Afkastfelter — advar hvis alle er None (tyder på parser-fejl)
        return_fields = ['return_1w', 'return_1m', 'return_3m', 'return_6m']
        none_count = sum(1 for f in return_fields if item.get(f) is None)
        if none_count == 4:
            warnings.append(f"ADVARSEL: {isin} ({name}) mangler alle afkasttal — mulig parser-fejl")
        elif none_count >= 2:
            missing = [f for f in return_fields if item.get(f) is None]
            warnings.append(f"ADVARSEL: {isin} ({name}) mangler {missing}")

        # Afkastsanity — ekstreme værdier tyder på parser-fejl
        for field in ['return_1w', 'return_1m', 'return_3m', 'return_6m', 'return_ytd', 'return_1y']:
            val = item.get(field)
            if val is not None:
                if val > RETURN_SANITY_MAX or val < RETURN_SANITY_MIN:
                    errors.append(
                        f"FEJL: {isin} ({name}) {field}={val}% er urealistisk "
                        f"(grænse: {RETURN_SANITY_MIN}% til {RETURN_SANITY_MAX}%)"
                    )

    # ==========================================
    # TJEK 2: Data er fra i dag (eller seneste hverdag)
    # ==========================================
    nav_dates = [item.get('nav_date') for item in latest if item.get('nav_date')]
    if nav_dates:
        most_recent = max(nav_dates)
        days_old = (datetime.strptime(today, '%Y-%m-%d') -
                    datetime.strptime(most_recent, '%Y-%m-%d')).days
        if days_old > 5:
            errors.append(
                f"FEJL: Data er {days_old} dage gammel (seneste nav_date: {most_recent}) "
                f"— PFA PDF-hentning fejlede sandsynligvis"
            )
        elif days_old > 1:
            warnings.append(
                f"INFO: Data er {days_old} dage gammel (nav_date: {most_recent}) "
                f"— kan skyldes weekend eller helligdag"
            )

    # ==========================================
    # TJEK 3: Aktive positioner i portefølje
    # ==========================================
    if portfolio:
        for isin, p_info in portfolio.items():
            if not p_info.get('active', False):
                continue
            name = p_info.get('name', isin)[:35]

            # Aktiv fond skal have buy_price
            if not p_info.get('buy_price') or p_info['buy_price'] <= 0:
                errors.append(f"FEJL: Aktiv fond {isin} ({name}) mangler buy_price")

            # Aktiv fond skal have buy_date
            if not p_info.get('buy_date'):
                warnings.append(f"ADVARSEL: Aktiv fond {isin} ({name}) mangler buy_date")

            # Aktiv fond skal findes i latest.json
            if isin not in latest_map:
                errors.append(
                    f"FEJL: Aktiv fond {isin} ({name}) mangler i latest.json "
                    f"— PFA leverer ikke data for denne fond"
                )

            # Aktiv fond skal have NAV
            elif not latest_map[isin].get('nav'):
                errors.append(f"FEJL: Aktiv fond {isin} ({name}) har ingen NAV i latest.json")

    # ==========================================
    # TJEK 4: history.json — kursspring
    # ==========================================
    jump_count = 0
    for isin, dates_dict in history.items():
        dates = sorted(dates_dict.keys())
        name  = latest_map.get(isin, {}).get('name', isin)[:35]

        # Min. antal datapunkter
        if len(dates) < MIN_HISTORY_POINTS:
            warnings.append(
                f"INFO: {isin} ({name}) har kun {len(dates)} historiske datapunkter "
                f"— MA-beregninger kan være upålidelige"
            )

        # Kursspring (kun for nærliggende datoer)
        for i in range(1, len(dates)):
            prev_price = dates_dict[dates[i-1]]
            curr_price = dates_dict[dates[i]]
            gap_days   = (datetime.strptime(dates[i], '%Y-%m-%d') -
                          datetime.strptime(dates[i-1], '%Y-%m-%d')).days

            if gap_days > 7:
                continue  # Spring over lange huller — ikke unormalt

            if prev_price <= 0:
                continue

            pct_change = abs((curr_price - prev_price) / prev_price)
            if pct_change > NAV_JUMP_PCT:
                jump_count += 1
                if jump_count <= 10:  # Vis max 10 for ikke at fylde loggen
                    errors.append(
                        f"FEJL: {isin} ({name}) kursspring {prev_price}→{curr_price} "
                        f"({pct_change*100:.1f}%) på {dates[i-1]}→{dates[i]} "
                        f"— mulig parser-fejl eller backfill-fejl"
                    )
    if jump_count > 10:
        errors.append(f"FEJL: {jump_count} kursspring >15% fundet i alt — se logfilen for detaljer")

    # ==========================================
    # TJEK 5: Konsistens mellem latest og history
    # ==========================================
    for item in latest:
        isin      = item.get('isin')
        nav       = item.get('nav')
        nav_date  = item.get('nav_date')
        name      = item.get('name', isin)[:35]

        if not (isin and nav and nav_date):
            continue

        if isin not in history:
            warnings.append(f"INFO: {isin} ({name}) har ingen historik endnu")
            continue

        hist_dates = sorted(history[isin].keys())
        if not hist_dates:
            continue

        # Seneste historik-kurs skal stemme med latest NAV (inden for 1 dag)
        latest_hist_date = hist_dates[-1]
        if latest_hist_date == nav_date:
            hist_nav = history[isin][latest_hist_date]
            diff = abs((nav - hist_nav) / hist_nav) if hist_nav else 0
            if diff > 0.001:  # Mere end 0.1% forskel
                warnings.append(
                    f"ADVARSEL: {isin} ({name}) latest NAV={nav} men history[{nav_date}]={hist_nav} "
                    f"— lille uoverensstemmelse ({diff*100:.2f}%)"
                )

    return errors, warnings


def validate_etf():
    """
    Validerer ETF-datafiler.
    Returnerer (kritiske_fejl, advarsler).
    """
    errors   = []
    warnings = []

    etf_latest    = load_json(ETF_LATEST_FILE)
    etf_history   = load_json(ETF_HISTORY_FILE)
    etf_portfolio = load_json(ETF_PORTFOLIO_FILE)
    etf_watchlist = load_json(ETF_WATCHLIST_FILE)

    # Filtrer kommentar-felter
    if isinstance(etf_portfolio, dict):
        etf_portfolio = {k: v for k, v in etf_portfolio.items() if not k.startswith('_')}
    if isinstance(etf_watchlist, dict):
        etf_watchlist = {k: v for k, v in etf_watchlist.items() if not k.startswith('_')}

    if etf_latest is None:
        errors.append(f"KRITISK ETF: {ETF_LATEST_FILE} mangler — etf_provider.py har ikke kørt")
        return errors, warnings
    if etf_history is None:
        errors.append(f"KRITISK ETF: {ETF_HISTORY_FILE} mangler")
        return errors, warnings

    today      = datetime.now().strftime('%Y-%m-%d')
    latest_map = {item['isin']: item for item in etf_latest if 'isin' in item}

    # ==========================================
    # ETF TJEK 1: etf_latest.json — grundfelter
    # ==========================================
    for item in etf_latest:
        isin = item.get('isin', '?')
        name = item.get('name', isin)[:35]

        if not item.get('nav') or item['nav'] <= 0:
            errors.append(f"FEJL ETF: {isin} ({name}) mangler NAV")

        if not item.get('nav_date'):
            errors.append(f"FEJL ETF: {isin} ({name}) mangler nav_date")

        if not item.get('ticker'):
            warnings.append(f"ADVARSEL ETF: {isin} ({name}) mangler ticker")

        # Afkastsanity — ETF'er kan have høje afkast (Korea +192%)
        # men ikke mere end 500%
        for field in ['return_1w', 'return_1m', 'return_1y', 'return_ytd']:
            val = item.get(field)
            if val is not None:
                if val > 500.0 or val < -90.0:
                    errors.append(
                        f"FEJL ETF: {isin} ({name}) {field}={val}% er urealistisk"
                    )

    # ==========================================
    # ETF TJEK 2: Data-alder
    # ==========================================
    nav_dates = [item.get('nav_date') for item in etf_latest if item.get('nav_date')]
    if nav_dates:
        most_recent = max(nav_dates)
        days_old = (datetime.strptime(today, '%Y-%m-%d') -
                    datetime.strptime(most_recent, '%Y-%m-%d')).days
        if days_old > ETF_MAX_DATA_AGE:
            errors.append(
                f"FEJL ETF: Data er {days_old} dage gammel (nav_date: {most_recent}) "
                f"— etf_provider.py fejlede sandsynligvis"
            )
        elif days_old > 1:
            warnings.append(
                f"INFO ETF: Data er {days_old} dage gammel — kan skyldes weekend"
            )

    # ==========================================
    # ETF TJEK 3: Aktive positioner
    # ==========================================
    if etf_portfolio:
        for isin, p_info in etf_portfolio.items():
            if not p_info.get('active', False):
                continue
            name = p_info.get('name', isin)[:35]

            if not p_info.get('buy_price') or p_info['buy_price'] <= 0:
                errors.append(f"FEJL ETF: Aktiv {isin} ({name}) mangler buy_price")

            if not p_info.get('ticker'):
                warnings.append(f"ADVARSEL ETF: Aktiv {isin} ({name}) mangler ticker")

            if isin not in latest_map:
                errors.append(
                    f"FEJL ETF: Aktiv {isin} ({name}) mangler i etf_latest.json"
                )

    # ==========================================
    # ETF TJEK 4: Historik — kursspring
    # ==========================================
    jump_count = 0
    for isin, dates_dict in etf_history.items():
        dates = sorted(dates_dict.keys())
        name  = latest_map.get(isin, {}).get('name', isin)[:35]

        if len(dates) < MIN_HISTORY_POINTS:
            warnings.append(
                f"INFO ETF: {isin} ({name}) har kun {len(dates)} datapunkter"
            )

        for i in range(1, len(dates)):
            prev_price = dates_dict[dates[i-1]]
            curr_price = dates_dict[dates[i]]
            gap_days   = (datetime.strptime(dates[i], '%Y-%m-%d') -
                          datetime.strptime(dates[i-1], '%Y-%m-%d')).days

            if gap_days > 7 or prev_price <= 0:
                continue

            pct_change = abs((curr_price - prev_price) / prev_price)
            if pct_change > ETF_NAV_JUMP_PCT:
                jump_count += 1
                if jump_count <= 5:
                    errors.append(
                        f"FEJL ETF: {isin} ({name}) kursspring "
                        f"{prev_price}→{curr_price} ({pct_change*100:.1f}%) "
                        f"på {dates[i-1]}→{dates[i]}"
                    )

    if jump_count > 5:
        errors.append(f"FEJL ETF: {jump_count} kursspring >{ETF_NAV_JUMP_PCT*100:.0f}% fundet")

    # ==========================================
    # ETF TJEK 5: Watchlist vs historik
    # ==========================================
    if etf_watchlist:
        for isin in etf_watchlist:
            name = etf_watchlist[isin].get('name', isin)[:35]
            if isin not in etf_history:
                warnings.append(
                    f"INFO ETF: {isin} ({name}) er i watchlist men mangler historik "
                    f"— etf_provider.py har ikke hentet data endnu"
                )
            if isin not in latest_map:
                warnings.append(
                    f"INFO ETF: {isin} ({name}) er i watchlist men mangler i etf_latest.json"
                )

    return errors, warnings


def main():
    print("\n" + "="*55)
    print("🔍 TRENDAGENT DATAVALIDERING")
    print("="*55)

    errors, warnings = validate()

    # Køer ETF-validering
    etf_errors, etf_warnings = validate_etf()
    errors   += etf_errors
    warnings += etf_warnings

    if warnings:
        print(f"\n⚠️  ADVARSLER ({len(warnings)}):")
        for w in warnings:
            print(f"   {w}")

    if errors:
        print(f"\n❌ KRITISKE FEJL ({len(errors)}):")
        for e in errors:
            print(f"   {e}")
        print(f"\n{'='*55}")
        print(f"Validering FEJLET — {len(errors)} kritiske fejl fundet.")
        print(f"{'='*55}\n")
        return len(errors)
    else:
        print(f"\n✅ Validering OK — ingen kritiske fejl.")
        if warnings:
            print(f"   {len(warnings)} advarsel(er) kræver ikke øjeblikkelig handling.")
        print(f"{'='*55}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
