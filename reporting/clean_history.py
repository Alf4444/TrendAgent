"""
clean_history.py — Renser forkerte kurser fra history.json
===========================================================
Køres ÉN gang manuelt efter en parser-fejl har forurenet historikken.

Problemet: Den gamle pfa.py parser fangede beholdningstal (fx 4.76%)
som NAV i stedet for den rigtige kurs (~426 USD). Disse forkerte lave
kurser er gemt i history.json og giver vanvittige afkasttal.

Strategi:
1. Brug latest.json som facit for hvad den rigtige kurs ca. er
2. For hver fond: beregn en acceptabel kurs-range baseret på latest NAV
3. Slet alle historiske punkter der falder UDEN for denne range
4. Gem den rensede history.json

Kør med: python reporting/clean_history.py
Eller med --dry-run for at se hvad der ville blive slettet uden at gøre det.
"""

import argparse
import json
from pathlib import Path

ROOT          = Path(__file__).resolve().parents[1]
HISTORY_FILE  = ROOT / "data/history.json"
LATEST_FILE   = ROOT / "data/latest.json"

# En kurs accepteres hvis den ligger inden for denne faktor af latest NAV.
# 0.5 = max 50% afvigelse fra nuværende kurs.
# Eksempel: latest NAV = 426 → accepteret range: 213 til 639
# Forkerte kurser på 4-10 vil blive slettet. Legitime kurser på 300-500 beholdes.
MAX_DEVIATION = 0.50


def clean_history(dry_run=False):
    if not HISTORY_FILE.exists():
        print(f"❌ Fandt ikke {HISTORY_FILE}")
        return

    if not LATEST_FILE.exists():
        print(f"❌ Fandt ikke {LATEST_FILE}")
        return

    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_list = json.load(f)
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)

    # Lav et map fra ISIN til latest NAV
    latest_map = {
        item["isin"]: item.get("nav")
        for item in latest_list
        if item.get("nav") and item["nav"] > 10  # Kun hvis latest NAV selv er gyldig
    }

    total_removed = 0
    total_kept    = 0
    funds_cleaned = 0

    for isin, prices in history.items():
        latest_nav = latest_map.get(isin)

        if latest_nav is None:
            print(f"⚠️  {isin}: Ingen gyldig latest NAV — springer over")
            continue

        lower = latest_nav * (1 - MAX_DEVIATION)
        upper = latest_nav * (1 + MAX_DEVIATION)

        dates_to_remove = [
            date for date, price in prices.items()
            if price < lower or price > upper
        ]

        if dates_to_remove:
            funds_cleaned += 1
            total_removed += len(dates_to_remove)
            total_kept    += len(prices) - len(dates_to_remove)

            print(f"\n{'[DRY RUN] ' if dry_run else ''}🧹 {isin}")
            print(f"   Latest NAV: {latest_nav} | Accepteret range: {lower:.2f} – {upper:.2f}")
            print(f"   Sletter {len(dates_to_remove)} punkter, beholder {len(prices) - len(dates_to_remove)}")

            # Vis eksempler på hvad der slettes
            examples = sorted(dates_to_remove)[:5]
            for d in examples:
                print(f"   ❌ {d}: {prices[d]}")
            if len(dates_to_remove) > 5:
                print(f"   ... og {len(dates_to_remove) - 5} flere")

            if not dry_run:
                for date in dates_to_remove:
                    del history[isin][date]
        else:
            total_kept += len(prices)

    print(f"\n{'=' * 50}")
    print(f"{'[DRY RUN] ' if dry_run else ''}Resultat:")
    print(f"  Fonde med fejl:    {funds_cleaned}")
    print(f"  Punkter slettet:   {total_removed}")
    print(f"  Punkter beholdt:   {total_kept}")

    if dry_run:
        print("\n[DRY RUN] Ingen ændringer gemt. Kør uden --dry-run for at rense.")
        return

    if total_removed == 0:
        print("\n✅ Ingen forkerte kurser fundet — history.json er allerede ren.")
        return

    # Gem renset historik
    for isin in history:
        history[isin] = dict(sorted(history[isin].items()))

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    print(f"\n✅ history.json renset og gemt.")
    print(f"   Kør daily workflow manuelt for at genopbygge med korrekte kurser.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Vis hvad der ville blive slettet uden at gøre det"
    )
    args = parser.parse_args()
    clean_history(dry_run=args.dry_run)
