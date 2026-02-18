# parser/pfa.py
import re

def parse_pfa_from_text(pfa_id, text):
    data = {
        "pfa_id": pfa_id,
        "nav": None,
        "nav_date": None,
        "currency": None
    }
    
    if not text:
        return data

    # Fjern alle mærkelige linjeskift og gør alt til ét langt stykke tekst
    # Dette løser problemet hvis "Indre værdi" er delt over to linjer
    clean_text = " ".join(text.split())

    # 1. FIND VALUTA
    # Vi kigger efter 'Valuta' efterfulgt af 3 store bogstaver
    curr_match = re.search(r"Valuta\s+([A-Z]{3})", clean_text, re.IGNORECASE)
    if curr_match:
        data["currency"] = curr_match.group(1).upper()

    # 2. FIND DATO (Kursdato)
    # I dine filer står der typisk "Indre værdi dato 17-02-2026"
    # Vi leder efter mønstret med bindestreger
    date_match = re.search(r"Indre\s+værdi\s+dato\s+(\d{2}-\d{2}-\d{4})", clean_text, re.IGNORECASE)
    if date_match:
        d = date_match.group(1).split("-")
        data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}" # Gem som 2026-02-17
    else:
        # Fallback: Hvis den bare finder en dato i nærheden af 'Indre værdi'
        date_fallback = re.search(r"(\d{2}-\d{2}-\d{4})", clean_text)
        if date_fallback:
            d = date_fallback.group(1).split("-")
            data["nav_date"] = f"{d[2]}-{d[1]}-{d[0]}"

    # 3. FIND NAV (Kursen)
    # Vi leder efter tallet der står efter "Indre værdi" (men ikke ordet "dato")
    # Vi leder efter et tal som f.eks. 115,00 eller 1.200,50
    nav_match = re.search(r"Indre\s+værdi\s+([\d\.,]+)", clean_text, re.IGNORECASE)
    if nav_match:
        val_str = nav_match.group(1)
        # Hvis tallet ender på et punktum eller komma pga. en sætning, fjerner vi det
        val_str = val_str.rstrip('.,')
        
        # Rens tallet: fjern tusindtals-punktum og skift komma til punktum
        if "," in val_str:
            val_str = val_str.replace(".", "").replace(",", ".")
        
        try:
            data["nav"] = float(val_str)
        except:
            pass

    return data
