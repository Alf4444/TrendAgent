import re

def parse_pfa_from_text(pfa_id, text):
    data = {
        "isin": pfa_id, 
        "name": None, 
        "nav": None, 
        "nav_date": None, 
        "currency": None, 
        "return_1w": "-", 
        "return_1m": "-", 
        "return_3m": "-", 
        "return_ytd": "-"
    }
    if not text: return data

    lines = text.split('\n')
    if lines:
        # Finder navnet på fonden (typisk første linje)
        data["name"] = lines[0].replace("Investeringsprofil Stamdata", "").strip()

    # Find Valuta
    cur_m = re.search(r"Valuta\s*\n?\s*([A-Z]{3})", text)
    if cur_m: data["currency"] = cur_m.group(1).upper()

    # Find Dato for indre værdi
    date_m = re.search(r"Indre\s+værdi\s+dato\s*\n?\s*(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # Find selve kursen (NAV)
    nav_m = re.search(r"Indre\s+værdi\s*\n?\s*([\d\.,]+)(?!\s*dato)", text, re.IGNORECASE)
    if nav_m:
        val_str = nav_m.group(1).rstrip('.,').replace(".", "").replace(",", ".")
        try: 
            # Vi konverterer til tal og afrunder til 2 decimaler
            data["nav"] = round(float(val_str), 2)
        except: 
            pass

    # Find Afkast-procenter (vi leder efter mønstre som 'X,XX%')
    # Typisk rækkefølge i PFA: 1u, 1m, 3m, 6m, ÅTD
    pct_matches = re.findall(r"(-?\d+,\d+)\s*%", text)
    if len(pct_matches) >= 5:
        data["return_1w"] = pct_matches[0]
        data["return_1m"] = pct_matches[1]
        data["return_3m"] = pct_matches[2]
        data["return_ytd"] = pct_matches[4]

    return data
