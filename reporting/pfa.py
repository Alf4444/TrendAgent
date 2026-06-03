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
        "aop": None,
        "sharpe_1y": None,
        "std_afv_1y": None,
        "top3_holdings": [],
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

    # STRATEGI: Find de to "Afdeling"-rækker direkte med MULTILINE regex.
    # PDF-layout i txt-filen:
    #   Afdeling  -0,28%  0,75%  -0,38%  -0,33%    ← RÆKKE 1: 1uge, 1md, 3md, 6md
    #   Benchmark ...
    #   Afdeling  -0,28%  0,99%  10,47%  -2,80%    ← RÆKKE 2: ÅTD, 1år, 3år, 5år
    #
    # Gammel regex fangede kun tekst EFTER anden "Afdeling" og fik derfor
    # kun ÅTD-rækken — og tildelte den forkerte feltnavne.

    # OBS: pdfplumber indsætter sommetider et sidetal foran "Afdeling"
    # fx "100 Afdeling -0,28% ..." — regex tillader derfor valgfrit præfiks
    afdeling_rows = re.findall(
        r"^(?:\d+\s+)?Afdeling\s+([-\d,\s%]+)",
        text,
        re.MULTILINE | re.IGNORECASE
    )

    if len(afdeling_rows) >= 2:
        row1_vals = re.findall(r"(-?\d+,\d+)", afdeling_rows[0])
        row2_vals = re.findall(r"(-?\d+,\d+)", afdeling_rows[1])

        r1_keys = ["return_1w", "return_1m", "return_3m", "return_6m"]
        for i, key in enumerate(r1_keys):
            if i < len(row1_vals):
                data[key] = to_float(row1_vals[i])

        if len(row2_vals) >= 1:
            data["return_ytd"] = to_float(row2_vals[0])
        if len(row2_vals) >= 2:
            data["return_1y"] = to_float(row2_vals[1])

    elif len(afdeling_rows) == 1:
        row1_vals = re.findall(r"(-?\d+,\d+)", afdeling_rows[0])
        r1_keys = ["return_1w", "return_1m", "return_3m", "return_6m"]
        for i, key in enumerate(r1_keys):
            if i < len(row1_vals):
                data[key] = to_float(row1_vals[i])

    else:
        # Ingen "Afdeling"-rækker fundet — fonden har sandsynligvis
        # et anderledes PDF-layout. Data forbliver None.
        print(f"[ADVARSEL] Ingen afkastdata fundet for {pfa_id}")

    # --- AOP, SHARPE, STD.AFV, TOP-3 BEHOLDNINGER ---
    data["aop"]           = _parse_aop(text)
    sharpe, std           = _parse_sharpe_std(text)
    data["sharpe_1y"]     = sharpe
    data["std_afv_1y"]    = std
    data["top3_holdings"] = _extract_top3_holdings(text)

    return data


# ==========================================
# NYE HJÆLPEFUNKTIONER — AOP, SHARPE, STD.AFV, TOP-3
# ==========================================

def _parse_aop(text):
    """Parser ÅOP — det 5. tal i omkostnings-blokken efter 'AOP' linjen."""
    m = re.search(
        r'AOP\s*\n([\d,]+)\s*\n([\d,]+)\s*\n([\d,]+)\s*\n([\d,]+)\s*\n([\d,]+)',
        text, re.IGNORECASE
    )
    if m:
        try:
            return round(float(m.group(5).replace(',', '.')), 2)
        except Exception:
            pass
    return None


def _parse_sharpe_std(text):
    """Parser Sharpe 1y og Std.afv 1y fra risiko-sektionen."""
    sharpe_1y = None
    std_afv_1y = None

    # Sharpe: første tal efter 'Sharpe\nStd. Afv.\n'
    m_sharpe = re.search(
        r'Sharpe\s*\n?\s*Std\.\s*Afv\.\s*\n([\d,]+)',
        text, re.IGNORECASE
    )
    if m_sharpe:
        try:
            sharpe_1y = round(float(m_sharpe.group(1).replace(',', '.')), 2)
        except Exception:
            pass

    # Std.afv 1y: første procent-tal på linjen efter de tre Sharpe-tal
    m_std = re.search(
        r'Sharpe\s*\n?\s*Std\.\s*Afv\.\s*\n[\d,]+\s+[\d,]+\s+[\d,]+\s*\n([\d,]+)%',
        text, re.IGNORECASE
    )
    if m_std:
        try:
            std_afv_1y = round(float(m_std.group(1).replace(',', '.')), 2)
        except Exception:
            pass

    return sharpe_1y, std_afv_1y


def _extract_top3_holdings(text):
    """Udtrækker de 3 største beholdninger fra faktaarkets beholdnings-sektion."""
    block_m = re.search(
        r'beholdninger[^\n]*\n(.+?)(?:Formuefordeling)',
        text, re.DOTALL
    )
    if not block_m:
        return []

    lines = [l.strip() for l in block_m.group(1).split('\n') if l.strip()]
    pairs = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Ren tal-linje: procent for foregående navn(e)
        if re.match(r'^\d+,\d+$', line) and i >= 1:
            name_parts = [lines[i-1]]
            if i >= 2:
                prev2 = lines[i-2]
                if not re.match(r'^\d', prev2) and not re.search(r'\d+,\d+', prev2):
                    name_parts.insert(0, prev2)
            pairs.append(' '.join(name_parts).strip())

        # Inline: 'Navn X,XX' eller 'Navn X,XX%'
        elif re.match(r'^.+\s+\d+,\d+%?$', line) and not re.match(r'^\d', line):
            name = re.sub(r'\s+\d+,\d+%?$', '', line).strip()
            # Tjek om forrige linje er del af dette navn (fx SAMSUNG NON)
            if i >= 1:
                prev = lines[i-1]
                if not re.match(r'^\d', prev) and not re.search(r'\d+,\d+', prev):
                    name = prev + ' ' + name
            pairs.append(name.strip())
        i += 1

    # Normaliser og filtrer
    skip = re.compile(r'(?i)(^cash|repo)')
    normalized = []
    for n in pairs:
        n = re.sub(r'\s+NON\s+VOTING\s+PRE\s*$', '', n, flags=re.IGNORECASE).strip()
        n = re.sub(r'^Ltd ADR\s*', '', n).strip()
        if n and not skip.search(n):
            normalized.append(n)

    return normalized[:3]
