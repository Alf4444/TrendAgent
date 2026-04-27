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
    if not text:
        return data

    lines = text.split('\n')
    if lines:
        # Finder navnet øverst i PFA PDF-teksten
        data["name"] = lines[0].replace("Investeringsprofil Stamdata", "").strip()

    # Find Valuta
    cur_m = re.search(r"Valuta\s*\n?\s*([A-Z]{3})", text)
    if cur_m:
        data["currency"] = cur_m.group(1).upper()

    # 1. Find Dato for indre værdi (format: DD-MM-YYYY)
    date_m = re.search(r"Indre\s+værdi\s+dato\s*(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # 2. Find selve kursen (NAV)
    # Negativt lookahead (?!dato) for at sikre vi ikke napper datoen som kurs
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

    # 3. AFKAST-PARSING — To rækker fra PFA's faktaark
    #
    # PDF-layoutet ser sådan ud:
    #   Afkast  1 uge  1 md.  3 md.  6 md.
    #   Afdeling
    #   Afkast  ÅTD  1 år  3 år  5 år
    #   Afdeling
    #   1,71%  8,83%  8,53%  21,93%        ← række 1: 1w, 1m, 3m, 6m
    #   17,37%  51,59%  90,09%  86,47%     ← række 2: ytd, 1y, 3y, 5y
    #
    # Vi finder begge "Afdeling"-blokke og henter tal fra dem begge.

    def to_float(val_str):
        try:
            return float(val_str.replace(",", "."))
        except:
            return None

    # Find alle tal-blokke der følger efter "Afdeling"
    # re.DOTALL så '.' matcher newlines
    afkast_block = re.search(
        r"Afdeling\s+([-?\d\.,\s%]+?)\s+Afdeling\s+([-?\d\.,\s%]+?)(?:\n[A-Za-zÆØÅæøå]|\Z)",
        text,
        re.DOTALL
    )

    if afkast_block:
        row1_vals = re.findall(r"(-?\d+,\d+)", afkast_block.group(1))
        row2_vals = re.findall(r"(-?\d+,\d+)", afkast_block.group(2))

        # Række 1: 1 uge, 1 md., 3 md., 6 md.
        if len(row1_vals) >= 4:
            data["return_1w"] = to_float(row1_vals[0])
            data["return_1m"] = to_float(row1_vals[1])
            data["return_3m"] = to_float(row1_vals[2])
            data["return_6m"] = to_float(row1_vals[3])
        elif len(row1_vals) > 0:
            # Delvis data — gem hvad vi har
            keys = ["return_1w", "return_1m", "return_3m", "return_6m"]
            for i, val in enumerate(row1_vals[:4]):
                data[keys[i]] = to_float(val)

        # Række 2: ÅTD, 1 år, 3 år, 5 år
        if len(row2_vals) >= 2:
            data["return_ytd"] = to_float(row2_vals[0])
            data["return_1y"]  = to_float(row2_vals[1])
            # 3 år og 5 år gemmes ikke da de ikke bruges i rapporterne endnu
    else:
        # Fallback: Gammel metode — forsøg med kun første Afdeling-blok
        # Bruges hvis PDF-layoutet afviger (f.eks. nyere fonde med færre data)
        afkast_match = re.search(r"Afdeling\s+([-?\d\.,\s%]+)", text)
        if afkast_match:
            raw_vals = re.findall(r"(-?\d+,\d+)", afkast_match.group(1))
            if len(raw_vals) >= 4:
                data["return_1w"] = to_float(raw_vals[0])
                data["return_1m"] = to_float(raw_vals[1])
                data["return_3m"] = to_float(raw_vals[2])
                data["return_6m"] = to_float(raw_vals[3])

    return data
