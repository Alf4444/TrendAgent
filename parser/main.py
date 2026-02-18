# parser/main.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import List, Dict, Set

from parser.pfa import parse_pfa_from_text  # forudsætter, at parser/pfa.py findes

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
TEXT_DIR = BUILD / "text"
DEBUG_DIR = BUILD / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
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

def _write_debug(isin: str, txt: str, parsed: Dict) -> None:
    lines = txt.splitlines()

    def _ctx(pattern: str) -> str:
        idxs = [i for i, ln in enumerate(lines) if re.search(pattern, ln, flags=re.IGNORECASE)]
        if not idxs:
            return "(label not found)"
        out = []
        for i in idxs[:2]:
            start = max(0, i - 5)
            end = min(len(lines), i + 6)
            block = "\n".join(f"{k+1:04d}: {lines[k]}" for k in range(start, end))
            out.append(block)
        return "\n---\n".join(out)

    nav_ctx = _ctx(r"Indre\s+værdi\b")
    date_ctx = _ctx(r"Indre\s+værdi\s+dato\b")

    report = [
        f"ISIN: {isin}",
        f"NAV_RAW: {parsed.get('nav_raw')}",
        f"NAV: {parsed.get('nav')}",
        f"NAV_DATE_RAW: {parsed.get('nav_date_raw')}",
        f"NAV_DATE: {parsed.get('nav_date')}",
        "",
        "=== Context: 'Indre værdi' ===",
        nav_ctx,
        "",
        "=== Context: 'Indre værdi dato' ===",
        date_ctx,
        "",
    ]
    (DEBUG_DIR / f"{isin}_extract.txt").write_text("\n".join(report), encoding="utf-8")

def main():
    print("[PARSE] ===== START parser.main =====")
    isins = _load_isins_from_config()
    if not isins:
        isins = _discover_isins_from_text()
    if not isins:
        isins = {"PFA000002738", "PFA000002735", "PFA000002761"}
        print("[PARSE] No ISINs discovered; using default 3 for now.")

    print(f"[PARSE] ISINs to process: {', '.join(sorted(isins))}")

    results: List[Dict] = []
    for isin in sorted(isins):
        txt = _load_text(isin)
        parsed = parse_pfa_from_text(isin, txt)
        results.append(parsed)
        _write_debug(isin, txt, parsed)

