import re

def parse_pfa_from_text(pfa_id, text):
    data = {
        "isin": pfa_id, 
        "name": None, 
        "nav": None, 
        "nav_date": None, 
        "currency": None, 
        "return_1w": None, 
        "return_1m": None, 
        "return_3m": None,
        "return_6m": None,
        "return_1y": None,
        "return_ytd": None
    }
    if not text: return data

    lines = text.split('\n')
    if lines:
        # Finder navnet øverst i PFA PDF-teksten
        data["name"] = lines[0].replace("Investeringsprofil Stamdata", "").strip()

    # Find Valuta
    cur_m = re.search(r"Valuta\s*\n?\s*([A-Z]{3})", text)
    if cur_m: data["currency"] = cur_m.group(1).upper()

    # Find Dato for indre værdi (format: DD-MM-YYYY)
    date_m = re.search(r"Indre\s+værdi\s+dato\s*\n?\s*(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # Find selve kursen (NAV) - håndterer både tusindtalsseparator og komma
    nav_m = re.search(r"Indre\s+værdi\s*\n?\s*([\d\.,]+)(?!\s*dato)", text, re.IGNORECASE)
    if nav_m:
        val_str = nav_m.group(1).rstrip('.,').replace(".", "").replace(",", ".")
        try: 
            data["nav"] = round(float(val_str), 2)
        except: 
            pass

    # --- AFKAST-PARSING ---
    # Finder alle procenttal i teksten
    pct_matches = re.findall(r"(-?\d+,\d+)\s*%", text)
    
    def to_float(val_str):
        try:
            return float(val_str.replace(",", "."))
        except:
            return None

    # PFA standard rækkefølge i afkast-tabellen: [1u, 1m, 3m, 6m, ÅTD, 1år]
    if len(pct_matches) >= 6:
        data["return_1w"] = to_float(pct_matches[0])
        data["return_1m"] = to_float(pct_matches[1])
        data["return_3m"] = to_float(pct_matches[2])
        data["return_6m"] = to_float(pct_matches[3])
        data["return_ytd"] = to_float(pct_matches[4])
        data["return_1y"] = to_float(pct_matches[5])
    elif len(pct_matches) == 5:
        # Hvis 1 år mangler i tabellen
        data["return_1w"] = to_float(pct_matches[0])
        data["return_1m"] = to_float(pct_matches[1])
        data["return_3m"] = to_float(pct_matches[2])
        data["return_6m"] = to_float(pct_matches[3])
        data["return_ytd"] = to_float(pct_matches[4])

    return data
