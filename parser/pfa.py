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
        data["name"] = lines[0].replace("Investeringsprofil Stamdata", "").strip()

    # Find Valuta
    cur_m = re.search(r"Valuta\s+([A-Z]{3})", text)
    if cur_m: data["currency"] = cur_m.group(1).upper()

    # 1. Find DATO (Vi gør den mere specifik så den ikke blandes med NAV)
    date_m = re.search(r"Indre\s+værdi\s+dato\s+(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # 2. Find NAV (Vi leder efter tallet der står lige efter 'Indre værdi' men IKKE efter 'dato')
    # Vi bruger et negativt lookahead for at sikre vi ikke tager datoen
    nav_patterns = [
        r"Indre\s+værdi\s+([\d\.,]+)(?!\s+dato)",
        r"Indre\s+værdi\s*\n\s*([\d\.,]+)"
    ]
    
    for pattern in nav_patterns:
        nav_m = re.search(pattern, text, re.IGNORECASE)
        if nav_m:
            val_str = nav_m.group(1).rstrip('.,').replace(".", "").replace(",", ".")
            try:
                data["nav"] = round(float(val_str), 2)
                break
            except:
                continue

    # 3. AFKAST (Meget mere robust - fjerner kravet om % tegn)
    # Vi leder efter sektionen 'Afdeling' og tager de tal der følger efter
    afkast_section = re.search(r"Afdeling\s+([-?\d\.,\s%]+)", text)
    if afkast_section:
        # Find alle tal (inkl. negative og med komma) i den sektion
        raw_vals = re.findall(r"(-?\d+,\d+)", afkast_section.group(1))
        
        def to_f(val_str):
            try: return float(val_str.replace(",", "."))
            except: return None

        if len(raw_vals) >= 4:
            data["return_1w"] = to_f(raw_vals[0])
            data["return_1m"] = to_f(raw_vals[1])
            data["return_3m"] = to_f(raw_vals[2])
            data["return_6m"] = to_f(raw_vals[3])

    return data
