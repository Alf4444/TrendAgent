# parser/pfa.py
import re

def parse_pfa_from_text(pfa_id, text):
    data = {
        "pfa_id": pfa_id,
        "nav": None,
        "nav_date": None,
        "currency": None
    }

    # 1. Valuta - kig efter 'Valuta' og derefter koden
    currency_match = re.search(r"Valuta\s+(DKK|EUR|USD)", text, re.IGNORECASE)
    if currency_match:
        data["currency"] = currency_match.group(1)

    # 2. Indre værdi (NAV) - vi kigger efter tallet lige efter 'Indre værdi'
    # Bemærk: Vi undgår 'Indre værdi dato' ved at bruge et negativt lookahead
    nav_match = re.search(r"Indre værdi\s+(?!dato)([\d\.,]+)", text, re.IGNORECASE)
    if nav_match:
        nav_str = nav_match.group(1).replace(".", "").replace(",", ".")
        try:
            data["nav"] = float(nav_str)
        except:
            pass

    # 3. Indre værdi dato - find datoen efter den specifikke overskrift
    date_match = re.search(r"Indre værdi dato\s+(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_match:
        d = date_match.group(1)
        parts = d.split("-")
        data["nav_date"] = f"{parts[2]}-{parts[1]}-{parts[0]}"
    
    # Debug print hvis data mangler
    if not data["nav"] or not data["nav_date"]:
        print(f"[DEBUG] Kunne ikke parse alt for {pfa_id}. NAV: {data['nav']}, Dato: {data['nav_date']}")

    return data
