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

    # 1. Find Dato for indre værdi (format: DD-MM-YYYY)
    date_m = re.search(r"Indre\s+værdi\s+dato\s*(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # 2. Find selve kursen (NAV)
    # Vi bruger et negativt lookahead (?!dato) for at sikre, at vi ikke napper datoen som en kurs
    nav_m = re.search(r"Indre\s+værdi\s+([\d\.,]+)(?!\s*dato)", text, re.IGNORECASE)
    if not nav_m:
        # Backup hvis layoutet er med linjeskift
        nav_m = re.search(r"Indre\s+værdi\s*\n\s*([\d\.,]+)", text, re.IGNORECASE)
        
    if nav_m:
        val_str = nav_m.group(1).rstrip('.,').replace(".", "").replace(",", ".")
        try: 
            data["nav"] = round(float(val_str), 2)
        except: 
            pass

    # 3. AFKAST-PARSING (Analytisk rettelse)
    # Vi finder linjen der starter med 'Afdeling' og henter alle tal-værdier efter den.
    # Dette gør os uafhængige af om der står '%' eller ej.
    afkast_match = re.search(r"Afdeling\s+([-?\d\.,\s%]+)", text)
    if afkast_match:
        # Find alle tal i formatet 'X,XX' eller '-X,XX'
        raw_vals = re.findall(r"(-?\d+,\d+)", afkast_match.group(1))
        
        def to_float(val_str):
            try:
                return float(val_str.replace(",", "."))
            except:
                return None

        # PFA standard rækkefølge i afkast-tabellen: [1u, 1m, 3m, 6m]
        if len(raw_vals) >= 4:
            data["return_1w"] = to_float(raw_vals[0])
            data["return_1m"] = to_float(raw_vals[1])
            data["return_3m"] = to_float(raw_vals[2])
            data["return_6m"] = to_float(raw_vals[3])

    return data
