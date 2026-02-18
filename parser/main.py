# parser/main.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Set

from parser.pfa import parse_pfa_from_text  # din eksisterende parser

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
TEXT_DIR = BUILD / "text"
OUT_DIR = ROOT / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CFG_ISINS = ROOT / "config" / "pfa_isins.json"

def _load_isins_from_config() -> Set[str]:
    if not CFG_ISINS.exists():
        return set()
    try:
        data = json.loads(CFG_ISINS.read_text(encoding="utf-8"))
        arr = data.get("isins", []) if isinstance(data, dict) else []
        return {str(x).strip() for x in arr if str(x).strip()}
    except Exception as e:
        print(f"[PARSE] Failed to load {CFG_ISINS}: {e}")
        return set()

def _discover_isins_from_text() -> Set[str]:
    if not TEXT_DIR.exists():
        return set()
    isins: Set[str] = set()
    for p in TEXT_DIR.glob("*.txt"):
        name = p.stem.strip()
        if name:
            isins.add(name)
    return isins

def _load_text(isin: str) -> str:
    p = TEXT_DIR / f"{isin}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8", errors="ignore")
    return ""

def main():
    # 1) ISIN-kilder: config → textfiler → fallback (3 standard)
    isins = _load_isins_from_config()
    if not isins:
        isins = _discover_isins_from_text()
    if not isins:
        isins = {"PFA000002738", "PFA000002735", "PFA000002761"}
        print("[PARSE] No ISINs discovered; using default 3 for now.")

    # 2) Parse
    results: List[Dict] = []
    for isin in sorted(isins):
        txt = _load_text(isin)
        parsed = parse_pfa_from_text(isin, txt)
        results.append(parsed)
        print(f"[PARSE] {isin}: NAV={parsed.get('nav')} NAVDato={parsed.get('nav_date')}")

    # 3) Skriv altid latest.json
    latest = {"funds": results}
    out_path = OUT_DIR / "latest.json"
    out_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[WRITE] {out_path} ({len(results)} fonde)")

if __name__ == "__main__":
    main()
