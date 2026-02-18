import re

def parse_pfa_from_text(pfa_id, text):
    data = {"pfa_id": pfa_id, "name": None, "nav": None, "nav_date": None, "currency": None}
    if not text: return data

    # 1. FIND NAVN (Hent første linje og rens den)
    lines = text.split('\n')
    if lines:
        data["name"] = lines[0].replace("Investeringsprofil Stamdata", "").strip()

    # 2. FIND VALUTA
    cur_m = re.search(r"Valuta\s*\n?\s*([A-Z]{3})", text)
    if cur_m:
        data["currency"] = cur_m.group(1).upper()

    # 3. FIND DATO
    date_m = re.search(r"Indre\s+værdi\s+dato\s*\n?\s*(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # 4. FIND NAV (Kursen)
    nav_m = re.search(r"Indre\s+værdi\s*\n?\s*([\d\.,]+)(?!\s*dato)", text, re.IGNORECASE)
    if nav_m:
        val_str = nav_m.group(1).rstrip('.,')
        if "," in val_str:
            val_str = val_str.replace(".", "").replace(",", ".")
        try:
            data["nav"] = float(val_str)
        except: pass

    return data
