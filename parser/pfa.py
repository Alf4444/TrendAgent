import re

def parse_pfa_from_text(pfa_id, text):
    data = {"pfa_id": pfa_id, "nav": None, "nav_date": None, "currency": None}
    if not text: return data

    # 1. FIND VALUTA (Leder efter Valuta linjen)
    cur_m = re.search(r"Valuta\s+([A-Z]{3})", text)
    if cur_m:
        data["currency"] = cur_m.group(1).upper()

    # 2. FIND DATO (Vi leder kun efter datoen efter "Indre værdi dato")
    # Dette sikrer vi ikke tager 'Største beholdninger' datoen i toppen
    date_m = re.search(r"Indre\s+værdi\s+dato\s+(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # 3. FIND NAV (Kursen)
    # Vi leder efter tallet umiddelbart efter "Indre værdi" (uden 'dato')
    # Regex kigger efter tal som 115,00 eller 408,00
    nav_m = re.search(r"Indre\s+værdi\s+([\d\.,]+)(?!\s*dato)", text, re.IGNORECASE)
    if nav_m:
        val_str = nav_m.group(1).rstrip('.,')
        # Hvis der er komma, er det dansk format: 1.200,50 -> 1200.50
        if "," in val_str:
            val_str = val_str.replace(".", "").replace(",", ".")
        try:
            data["nav"] = float(val_str)
        except:
            pass

    return data
