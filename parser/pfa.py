# parser/pfa.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import re
import unicodedata
from typing import Dict, Optional, List
from datetime import datetime

__all__ = ["extract_stamdata", "parse_pfa_from_text"]

def _normalize_text(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\x0c", "\n")
    return s

def _norm_number_auto(raw: str) -> Optional[float]:
    if not raw: return None
    # Fjern alt undtagen tal, komma og punktum
    s = re.sub(r"[^0-9\.,]", "", raw.strip())
    if not s: return None
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def _norm_date_to_iso(raw: str) -> Optional[str]:
    if not raw: return None
    m = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{4})", raw)
    if not m: return None
    dd, mm, yyyy = m.groups()
    try:
        return datetime(int(yyyy), int(mm), int(dd)).strftime("%Y-%m-%d")
    except ValueError:
        return None

def extract_stamdata(raw_text: str) -> Dict[str, Optional[str]]:
    text = _normalize_text(raw_text)
    
    # Find blokken efter "Stamdata" (vi tager de næste 2000 tegn)
    m = re.search(r"Stamdata", text, re.IGNORECASE)
    if not m:
        return {}
    
    context = text[m.end():m.end()+2000]
    lines = [ln.strip() for ln in context.splitlines() if ln.strip()]
    
    res = {
        "Valuta": None,
        "Indre værdi": None,
        "Indre værdi dato": None
    }
    
    # 1. Find Valuta (Kig efter EUR, DKK eller USD)
    for ln in lines:
        curr_match = re.search(r"\b(EUR|DKK|USD)\b", ln)
        if curr_match:
            res["Valuta"] = curr_match.group(1)
            break
            
    # 2. Find Dato (dd-mm-yyyy)
    for ln in lines:
        date_iso = _norm_date_to_iso(ln)
        if date_iso:
            # Vi gemmer den rå dato her, parse_pfa_from_text konverterer den senere
            res["Indre værdi dato"] = ln 
            break

    # 3. Find Indre Værdi (NAV)
    # Vi leder efter et tal med komma (f.eks. 154,64) der ikke er en dato
    for ln in lines:
        # Spring linjer over der ligner datoer eller årstal
        if re.search(r"\d{2}-\d{2}-\d{4}", ln) or ln in ["2022", "2023", "2024", "2025", "2026"]:
            continue
        num = _norm_number_auto(ln)
        if num and num > 10: # NAV er typisk over 10, undgå små tal som "8" (bæredygtighed)
            res["Indre værdi"] = ln
            break
            
    return res

def parse_pfa_from_text(pfa_code: str, text: str) -> Dict[str, Optional[str]]:
    sd = extract_stamdata(text or "")
    
    nav_raw = sd.get("Indre værdi")
    nav = _norm_number_auto(nav_raw)
    
    date_raw = sd.get("Indre værdi dato")
    nav_date = _norm_date_to_iso(date_raw)

    return {
        "pfa_code": pfa_code,
        "nav": nav,
        "nav_date": nav_date,
        "currency": sd.get("Valuta"),
    }
