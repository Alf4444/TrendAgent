import re

def parse_pfa_from_text(pfa_id, text):
    data = {
        "pfa_id": pfa_id, "name": None, "nav": None, "nav_date": None, 
        "currency": None, "return_1w": "-", "return_1m": "-", "return_3m": "-", "return_ytd": "-"
    }
    if not text: return data

    lines = text.split('\n')
    if lines:
        data["name"] = lines[0].replace("Investeringsprofil Stamdata", "").strip()

    # Find NAV, Dato og Valuta
    cur_m = re.search(r"Valuta\s*\n?\s*([A-Z]{3})", text)
    if cur_m: data["currency"] = cur_m.group(1).upper()

    date_m = re.search(r"Indre\s+værdi\s+dato\s*\n?\s*(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    nav_m = re.search(r"Indre\s+værdi\s*\n?\s*([\d\.,]+)(?!\s*dato)", text, re.IGNORECASE)
    if nav_m:
        val_str = nav_m.group(1).rstrip('.,').replace(".", "").replace(",", ".")
        try: data["nav"] = float(val_str)
        except: pass

    # Find Afkast-rækken (vi leder efter mønstre som 'X,XX%')
    # Vi tager de første 5 procenter fundet i teksten, da de ofte matcher 1u, 1m, 3m, 6m, ÅTD
    pct_matches = re.findall(r"(-?\d+,\d+)\s*%", text)
    if len(pct_matches) >= 5:
        data["return_1w"] = pct_matches[0]
        data["return_1m"] = pct_matches[1]
        data["return_3m"] = pct_matches[2]
        data["return_ytd"] = pct_matches[4] # ÅTD er typisk nr. 5

    return data
