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
    # NAV står i faktaarket sådan:
    #   Indre værdi dato 24-04-2026
    #   Bæredygtighed Artikel 8
    #   426,56                        ← NAV
    #   Afkast 1 uge ...
    #
    # Strategi: Find NAV som det FØRSTE store tal (> 10) der optræder
    # efter "Indre værdi dato" og FØR "Afkast 1 uge".
    # Det forhindrer at vi fanger beholdningstal (typisk 1-5%) som NAV.

    nav_section = re.search(
        r"Indre\s+v[æe]rdi\s+dato.*?(?=Afkast\s+1\s+uge)",
        text, re.IGNORECASE | re.DOTALL
    )

    if nav_section:
        # Find alle tal i sektionen — NAV er det største
        candidates = re.findall(r"([\d\.]+,\d+)", nav_section.group(0))
        for c in candidates:
            val_str = c.rstrip('.,').replace(".", "").replace(",", ".")
            try:
                val = float(val_str)
                # NAV er altid > 10 — beholdningstal er typisk 1-5%
                if val > 10:
                    data["nav"] = round(val, 2)
                    break
            except Exception:
                continue

    if not data["nav"]:
        # Fallback: tag det største tal i hele teksten mellem dato og afkast
        nav_m = re.search(
            r"Indre\s+v[æe]rdi\b(?!\s+dato)\s+([\d\.]+,\d+)",
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

    # Find afkast-sektionen: fra første "Afkast 1 uge" til "Sharpe" eller slutningen
    # OBS: Tallene kommer EFTER "Omkostninger"-sektionen i PFA's PDF-layout,
    # så vi må ikke stoppe ved "Omkostninger" — vi stopper ved "Sharpe" eller "Største"
    afkast_section_m = re.search(
        r"Afkast\s+1\s+uge.*?Afdeling.*?Afdeling(.*?)(?:Sharpe|Største\s+beholdninger|\Z)",
        text,
        re.DOTALL | re.IGNORECASE
    )

    if afkast_section_m:
        tail = afkast_section_m.group(1)
        # Filtrer omkostningslinjer fra — de indeholder typisk meget lave tal (0-2)
        # Afkasttal er enten negative eller positive og typisk ikke 0,00
        # Vi finder kun tal der IKKE er på linjer med "omkostninger", "gebyr" eller "ÅOP"
        clean_lines = []
        for line in tail.split('\n'):
            line_lower = line.lower()
            if any(w in line_lower for w in ['omkostning', 'gebyr', 'åop', 'transaktions', 'oprettelses', 'udtrædelses']):
                continue
            clean_lines.append(line)
        clean_tail = '\n'.join(clean_lines)
        all_vals = re.findall(r"(-?\d+,\d+)", clean_tail)

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
