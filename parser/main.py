import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from pfa import parse_pfa_from_text

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build/text"
OUT_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
CONFIG_FILE = ROOT / "config/pfa_pdfs.json"

# Maksimalt tilladt dagligt kurs-hop i % før vi afviser datapunktet.
# Sat til 15% — dækker selv volatile EM-fonde og guld/råvare-fonde
# på en normal handelsdag. Ændres kun hvis vi ser falske positiver.
VOLATILITY_GUARD_PCT = 0.15


def calculate_backfill(nav, nav_date_str, returns):
    """
    Beregner historiske kurspunkter baglæns baseret på officielle afkasttal.
    Bruges til at bootstrappe historik for nyoprettede fonde i systemet.

    VIGTIGT: Backfill-punkter må aldrig overskrive eksisterende rigtige data.
    De bruges KUN til at fylde huller ud, så MA-beregninger kan starte hurtigere.

    Formel: hist_kurs = nuværende_kurs / (1 + afkast_pct/100)
    """
    backfill = {}
    try:
        current_date = datetime.strptime(nav_date_str, '%Y-%m-%d')
    except Exception:
        current_date = datetime.now()

    # Vi bruger return_1y til at lave et backfill-punkt 365 dage tilbage.
    # De øvrige intervaller er afkast vi allerede har fra PFA's faktaark.
    intervals = {
        '1w':  7,
        '1m':  30,
        '3m':  91,
        '6m':  182,
        '1y':  365,
    }

    for key, days in intervals.items():
        pct = returns.get(f'return_{key}')
        if pct is not None and isinstance(pct, (int, float)):
            hist_price = nav / (1 + (pct / 100))
            hist_date = (current_date - timedelta(days=days)).strftime('%Y-%m-%d')
            backfill[hist_date] = round(hist_price, 2)

    return backfill


def main():
    if not CONFIG_FILE.exists():
        print(f"❌ Config fil mangler: {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        isins = json.load(f)

    active_isins = [i.strip() for i in isins if not i.strip().startswith(("#", "-"))]
    results = []

    history = {}
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = {}

    for isin in active_isins:
        txt_file = TEXT_DIR / f"{isin}.txt"
        data = {"isin": isin, "name": "Mangler data", "nav": None, "nav_date": None}

        if txt_file.exists():
            text = txt_file.read_text(encoding="utf-8", errors="ignore")
            parsed = parse_pfa_from_text(isin, text)
            data.update(parsed)

            if data["nav"] and data["nav_date"]:
                if isin not in history:
                    history[isin] = {}

                # --- VOLATILITY GUARD ---
                # Sammenligner KUN mod eksisterende rigtige datapunkter.
                # Vi sorterer og bruger seneste dato — men springer over
                # backfill-estimater ved at se om den seneste dato er "gammel"
                # (dvs. mere end 10 dage tilbage = formentlig et backfill-punkt).
                #
                # RETTELSE ift. tidligere version: Den gamle guard sammenlignede
                # mod backfill-datoer langt tilbage i tid, som kunne give meget
                # store spring og blokere for legitime nye datapunkter.
                real_dates = sorted([
                    d for d in history[isin].keys()
                    if d <= data["nav_date"]  # Ignorer fremtidige datoer (burde ikke ske)
                ])

                if real_dates:
                    # Find den senest registrerede kurs inden for de sidste 10 dage
                    # (backfill-punkter fra 30/91/182/365 dage siden springes over)
                    recent_threshold = (
                        datetime.strptime(data["nav_date"], '%Y-%m-%d') - timedelta(days=10)
                    ).strftime('%Y-%m-%d')

                    recent_dates = [d for d in real_dates if d >= recent_threshold]

                    if recent_dates:
                        last_date = recent_dates[-1]
                        last_nav = history[isin][last_date]
                        diff = abs((data["nav"] - last_nav) / last_nav)

                        if diff > VOLATILITY_GUARD_PCT:
                            print(
                                f"⚠️  Volatility Guard: {isin} ({data.get('name', '')}) "
                                f"afvist: {last_nav} → {data['nav']} "
                                f"({diff*100:.1f}% ændring på {last_date} → {data['nav_date']})"
                            )
                            # Vi tilføjer stadig fonden til results (med nuværende data)
                            # men gemmer IKKE kursen i historikken denne gang.
                            results.append(data)
                            continue

                # --- GEM KUN NYE DATA ---
                if data["nav_date"] not in history[isin]:
                    history[isin][data["nav_date"]] = data["nav"]
                    print(f"[NY KURS] {isin}: {data['nav']} ({data['nav_date']})")

                # --- BACKFILL ---
                # Udfylder historiske huller baseret på officielle afkasttal.
                # Overskriv ALDRIG eksisterende datapunkter.
                historical_points = calculate_backfill(data["nav"], data["nav_date"], data)
                added_backfill = 0
                for h_date, h_nav in historical_points.items():
                    if h_date not in history[isin]:
                        history[isin][h_date] = h_nav
                        added_backfill += 1
                if added_backfill > 0:
                    print(f"[BACKFILL] {isin}: {added_backfill} historiske punkter tilføjet")

        results.append(data)

    # --- GEM & RYD OP ---
    OUT_FILE.parent.mkdir(exist_ok=True)

    # Sorter datoer i historikken
    for isin in history:
        history[isin] = dict(sorted(history[isin].items()))

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print(f"✅ Main færdig: {len(results)} fonde behandlet, historik opdateret.")


if __name__ == "__main__":
    main()
