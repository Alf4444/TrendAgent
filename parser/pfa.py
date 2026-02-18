# parser/pfa.py
import re

def parse_pfa_from_text(pfa_id, text):
    data = {
        "pfa_id": pfa_id,
        "nav": None,
        "nav_date": None,
        "currency": None
    }
    
    if not text: return data

    # Fjerner alle mærkelige linjeskift og dobbelt-mellemrum
    clean = " ".join(text.split())

    # 1. Valuta (DKK, EUR, USD)
    cur_m = re.search(r"Valuta\s+(DKK|EUR|USD)", clean, re.IGNORECASE)
    if cur_m: data["currency"] = cur_m.group(1).upper()

    # 2. Indre værdi dato (Kursdatoen) - Vi leder efter DD-MM-ÅÅÅÅ
    date_m = re.search(r"Indre\s+værdi\s+dato\s+(\d{2}-\d{2}-\d{4})", clean, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}" # Gemmer som ÅÅÅÅ-MM-DD

    # 3. Indre værdi (NAV) - Vi tager tallet efter "Indre værdi"
    # Vi bruger et negativt lookahead for at sikre vi ikke tager datoen her
    nav_m = re.search(r"Indre\s+værdi\s+(?!dato)([\d\.,]+)", clean, re.IGNORECASE)
    if nav_m:
        val = nav_m.group(1).replace(".", "").replace(",", ".")
        try:
            data["nav"] = float(val)
        except: pass

    return data
