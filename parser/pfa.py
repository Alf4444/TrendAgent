# parser/pfa.py
import re

def parse_pfa_from_text(pfa_id, text):
    """
    Ekstraherer NAV, dato og valuta fra PFA faktaark-tekst.
    """
    data = {
        "pfa_id": pfa_id,
        "nav": None,
        "nav_date": None,
        "currency": None
    }

    # 1. Find Valuta (Kigger efter linjen 'Valuta' efterfulgt af DKK, EUR eller USD)
    currency_match = re.search(r"Valuta\s+(DKK|EUR|USD)", text)
    if currency_match:
        data["currency"] = currency_match.group(1)

    # 2. Find Indre værdi (NAV)
    # Leder efter 'Indre værdi' efterfulgt af et tal (f.eks. 115,00)
    nav_match = re.search(r"Indre værdi\s+([\d\.,]+)", text)
    if nav_match:
        nav_str = nav_match.group(1).replace(".", "").replace(",", ".")
        try:
            data["nav"] = float(nav_str)
        except:
            pass

    # 3. Find Indre værdi dato (Den faktiske kursdato)
    # Leder specifikt efter datoen efter 'Indre værdi dato'
    date_match = re.search(r"Indre værdi dato\s+(\d{2}-\d{2}-\d{4})", text)
    if date_match:
        # Konverterer 17-02-2026 til ISO format 2026-02-17
        d = date_match.group(1)
        parts = d.split("-")
        data["nav_date"] = f"{parts[2]}-{parts[1]}-{parts[0]}"

    return data
