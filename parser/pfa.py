import re

def parse_pfa_from_text(pfa_id, text):
    data = {"pfa_id": pfa_id, "nav": None, "nav_date": None, "currency": None}
    if not text: return data

    # 1. FIND VALUTA
    # Vi leder efter Valuta efterfulgt af DKK/EUR/USD
    cur_m = re.search(r"Valuta\s+(DKK|EUR|USD)", text)
    if cur_m:
        data["currency"] = cur_m.group(1).upper()

    # 2. FIND DATO (Indre værdi dato)
    # Vi kigger specifikt efter formatet DD-MM-ÅÅÅÅ efter ordet 'dato'
    date_m = re.search(r"Indre\s+værdi\s+dato\s+(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # 3. FIND NAV (Indre værdi)
    # Vi leder efter tallet der står efter "Indre værdi" men som IKKE følges af ordet "dato"
    # Vi bruger en regex der fanger tal som 115,00 eller 1.200,50
    nav_patterns = [
        r"Indre\s+værdi\s+(?!dato\b)([\d\.,]+)",
        r"Indre\s+værdi\n([\d\.,]+)"
    ]
    
    for pattern in nav_patterns:
        nav_m = re.search(pattern, text, re.IGNORECASE)
        if nav_m:
            val_str = nav_m.group(1).rstrip('.,')
            # Rens tallet: fjern punktum (tusindtal) og gør komma til punktum (decimal)
            if "," in val_str:
                val_str = val_str.replace(".", "").replace(",", ".")
            try:
                data["nav"] = float(val_str)
                break 
            except:
                continue

    return data
