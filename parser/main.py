# parser/main.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import List, Dict, Set

from parser.pfa import parse_pfa_from_text

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
    """
    Skriv en lille debug-fil pr. ISIN med match-kontekst.
    """
    lines = txt.splitlines()
    def _ctx(pattern: str) -> str:
        idxs = [i for i, ln in enumerate(lines) if re.search(pattern, ln, flags=re.IGNORECASE)]
        if not idxs:
            return "(label not found)"
        out = []
        for i in idxs[:2]:  # max to hits
            start = max(0, i - 5)
            end = min(len(lines), i + 6)
