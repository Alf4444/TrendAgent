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
        "return_ytd": None,
    }
    if not text:
        return data

    lines = text.split('\n')
    if lines:
        # Finder navnet øverst i PFA PDF-teksten
        data["name"] = lines[0].replace("Investeringsprofil Stamdata", "").strip()

    # --- VALUTA ---
    cur_m = re.search(r"Valuta\s*\n?\s*([A-Z]{3})", text)
    if cur_m:
        data["currency"] = cur_m.group(1).upper()

    # --- NAV DATO (format: DD-MM-YYYY) ---
    date_m = re.search(r"Indre\s+v[æe]rdi\s+dato\s*(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    if date_m:
        d = date_m.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # --- NAV (indre værdi) ---
    # Vi leder efter "Indre værdi" efterfulgt af et tal (ikke datoen).
    # pdfplumber kan placere NAV-værdien på samme linje eller næste linje.
    nav_m = re.search(
        r"Indre\s+v[æe]rdi\s+dato[^\n]*\n.*?\n\s*([\d\.]+,\d+)",
        text, re.IGNORECASE | re.DOTALL
    )
    if not nav_m:
        # Fallback: NAV på samme linje som "Indre værdi" men ikke datoen
        nav_m = re.search(
            r"Indre\s+v[æe]rdi\b(?!\s+dato)\s+([\d\.]+,\d+)",
            text, re.IGNORECASE
        )
    if not nav_m:
        # Sidste fallback: find standalone tal efter "Bæredygtighed" linjen
        nav_m = re.search(
            r"B[æe]redygtighed[^\n]*\n\s*([\d\.]+,\d+)",
            text, re.IGNORECASE
        )

    if nav_m:
        val_str = nav_m.group(1).rstrip('.,').replace(".", "").replace(",", ".")
        try:
            data["nav"] = round(float(val_str), 2)
        except Exception:
            pass

    # --- AFKAST-PARSING ---
    #
    # PFA's faktaark har to afkast-blokke:
    #
    #   Afkast  1 uge  1 md.  3 md.  6 md.
    #   Afdeling
    #   Afkast  ÅTD  1 år  3 år  5 år
    #   Afdeling
    #   Omkostninger % ...
    #   1,71%  8,83%  8,53%  21,93%        ← række 1: 1w, 1m, 3m, 6m
    #   17,37%  51,59%  90,09%  86,47%     ← række 2: ytd, 1y, 3y, 5y
    #
    # VIGTIGT: pdfplumber samler al tekst og lader tallene falde til sidst —
    # de to talrækker kommer EFTER begge "Afdeling"-linjer, ikke imellem dem.
    # Strategien er derfor:
    #   1. Find blokken der starter med første "Afkast" og slutter ved "Omkostninger"
    #   2. Udtræk alle kommatal fra den blok
    #   3. Tildel tal til de rigtige felter baseret på rækkefølge

    def to_float(s):
        try:
            return round(float(s.replace(",", ".")), 2)
        except Exception:
            return None

    # Find afkast-sektionen: fra første "Afkast" til "Omkostninger"
    afkast_section_m = re.search(
        r"(Afkast\s+1\s+uge.*?Afdeling.*?Afdeling)(.*?)(?:Omkostninger|ÅOP|Sharpe|\Z)",
        text,
        re.DOTALL | re.IGNORECASE
    )

    if afkast_section_m:
        # Gruppen efter de to "Afdeling"-linjer indeholder tallene
        tail = afkast_section_m.group(2)
        all_vals = re.findall(r"(-?\d+,\d+)", tail)

        # Forventet rækkefølge: 1w, 1m, 3m, 6m, ytd, 1y, 3y, 5y
        keys = [
            "return_1w", "return_1m", "return_3m", "return_6m",
            "return_ytd", "return_1y",
            # 3y og 5y ignoreres (ikke brugt endnu)
        ]
        for i, key in enumerate(keys):
            if i < len(all_vals):
                data[key] = to_float(all_vals[i])

    else:
        # --- FALLBACK STRATEGI ---
        # Bruges hvis PDF-layoutet afviger (fx nyere fonde med færre data).
        # Vi finder de to "Afdeling"-blokke separat og udtrækker tal fra dem.

        # Find alle forekomster af "Afdeling" og hvad der følger
        afdeling_matches = list(re.finditer(r"Afdeling\s+([-?\d\.,\s%]+)", text))

        if len(afdeling_matches) >= 2:
            row1_vals = re.findall(r"(-?\d+,\d+)", afdeling_matches[0].group(1))
            row2_vals = re.findall(r"(-?\d+,\d+)", afdeling_matches[1].group(1))

            # Række 1: 1 uge, 1 md., 3 md., 6 md.
            r1_keys = ["return_1w", "return_1m", "return_3m", "return_6m"]
            for i, key in enumerate(r1_keys):
                if i < len(row1_vals):
                    data[key] = to_float(row1_vals[i])

            # Række 2: ÅTD, 1 år (3 år og 5 år ignoreres)
            if len(row2_vals) >= 1:
                data["return_ytd"] = to_float(row2_vals[0])
            if len(row2_vals) >= 2:
                data["return_1y"] = to_float(row2_vals[1])

        elif len(afdeling_matches) == 1:
            # Kun én blok — tag hvad vi kan (række 1 kun)
            raw_vals = re.findall(r"(-?\d+,\d+)", afdeling_matches[0].group(1))
            r1_keys = ["return_1w", "return_1m", "return_3m", "return_6m"]
            for i, key in enumerate(r1_keys):
                if i < len(raw_vals):
                    data[key] = to_float(raw_vals[i])

    return data
