# parser/parse_pfa.py
"""
Formål (fase 1):
- Indlæse data/funds.csv
- (Valgfrit i første kørsel) Mocke 'latest' data
- Gemme latest.json i repo (eller i workflow-artifact-mappen)

Fase 2:
- Downloade PFA PDF'er
- Parse "Indre værdi" + "Indre værdi dato" via pdfminer.six
- Opdatere Google Sheets (Latest/History)

Kørsel:
python parser/parse_pfa.py --out latest.json --mock
"""

import argparse
import csv
import json
from datetime import date

def load_funds(path="data/funds.csv"):
    funds = []
    with open(path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            if row.get("isin"):
                funds.append({"isin": row["isin"], "source_url": row.get("source_url", "")})
    return funds

def build_mock_latest(funds):
    # Simpel mock: samme NAV for alle, med lidt variation
    base_nav = 100.0
    res = []
    for i, f in enumerate(funds):
        nav = base_nav + i * 0.37  # lille variation
        res.append({
            "isin": f["isin"],
            "nav": round(nav, 2),
            "nav_date": date.today().isoformat(),
            # dummy felter til daglig rapport
            "change_pct": 0.0,
            "trend_shift": False,
            "cross_20_50": False,
            "trend_state": "NEUTRAL",
        })
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="latest.json")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    funds = load_funds()
    if args.mock:
        latest = build_mock_latest(funds)
    else:
        # TODO (fase 2): download PDF & parse via pdfminer
        latest = build_mock_latest(funds)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"rows": latest, "run_date": date.today().isoformat()}, f, ensure_ascii=False, indent=2)

    print(f"Wrote {args.out} with {len(latest)} rows")

if __name__ == "__main__":
    main()
