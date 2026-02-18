# parser/main.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict
from parser.pfa import parse_pfa_from_text

BUILD = Path("build")
TEXT_DIR = BUILD / "text"
OUT_DIR = Path("data")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _discover_isins_from_text() -> List[str]:
    """
    Finder alle *.txt i build/text og gætter ISIN (filnavn uden .txt).
    Sorterer for deterministisk output.
    """
    if not TEXT_DIR.exists():
        return []
    isins = []
    for p in TEXT_DIR.glob("*.txt"):
        name = p.stem.strip()
        if name:
            isins.append(name)
    return sorted(isins)


def _load_text(isin: str) -> str:
    p = TEXT_DIR / f"{isin}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def main():
    isins = _discover_isins_from_text()
    # Fallback hvis autodiscovery intet finder (hold jeres standard 3)
    if not isins:
        isins = ["PFA000002738", "PFA000002735", "PFA000002761"]

    results: List[Dict] = []
    for isin in isins:
        txt = _load_text(isin)
        parsed = parse_pfa_from_text(isin, txt)
        results.append(parsed)
        # Kort log for Actions
        nav = parsed.get("nav")
        nav_date = parsed.get("nav_date")
        print(f"[PARSE] {isin}: NAV={nav} NAVDato={nav_date}")

    latest = {"funds": results}
    out_path = OUT_DIR / "latest.json"
    out_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[WRITE] {out_path} ({len(results)} fonde)")

    # Parse-debug artifact håndteres i workflow (upload af build/text/ og build/pdf/)

if __name__ == "__main__":
    main()
