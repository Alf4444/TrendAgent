"""
=============================================================================
TRENDAGENT PORTFOLIO MANAGER - MANUAL
=============================================================================
Dette script bruges til at styre dine aktive fonde uden at rette i JSON-filer.

SÅDAN BRUGER DU TERMINALEN:

1. KØB: Registrerer en ny fond eller opdaterer købskursen på en eksisterende.
   Kommando: python manage_portfolio.py buy [ISIN] [KURS]
   Eksempel: python manage_portfolio.py buy PFA000002703 415.21

2. SALG: Sætter en fond som inaktiv og gemmer dags dato som salgsdato.
   Kommando: python manage_portfolio.py sell [ISIN]
   Eksempel: python manage_portfolio.py sell PFA000002735

Husk at bruge PUNKTUM som decimaltegn (f.eks. 123.45).
=============================================================================
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# STIER - Finder automatisk mapperne uanset hvor scriptet køres fra
ROOT = Path(__file__).resolve().parent
PORTFOLIO_FILE = ROOT / "config" / "portfolio.json"
LATEST_DATA = ROOT / "data" / "latest.json"

def load_json(path):
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_portfolio(data):
    PORTFOLIO_FILE.parent.mkdir(exist_ok=True)
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_fund_name(isin):
    """Slår navnet op i data/latest.json hvis det er en ny fond."""
    latest = load_json(LATEST_DATA)
    if isinstance(latest, list):
        for item in latest:
            if item.get('isin') == isin:
                return item.get('name', isin)
    return isin

def show_help():
    """Viser en hjælpsom guide i terminalen."""
    print("\n" + "="*45)
    print("🚀 TRENDAGENT - HJÆLP TIL PORTEFØLJE")
    print("="*45)
    print("Brug en af følgende kommandoer:\n")
    print("  python manage_portfolio.py buy [ISIN] [KURS]")
    print("  python manage_portfolio.py sell [ISIN]")
    print("\nEKSEMPLER:")
    print("  python manage_portfolio.py buy PFA000002703 420.50")
    print("  python manage_portfolio.py sell PFA000002735")
    print("="*45 + "\n")

def buy(isin, price):
    portfolio = load_json(PORTFOLIO_FILE)
    name = portfolio.get(isin, {}).get('name') or get_fund_name(isin)
    
    portfolio[isin] = {
        "name": name,
        "active": True,
        "buy_date": datetime.now().strftime("%Y-%m-%d"),
        "buy_price": float(price)
    }
    
    if "sell_date" in portfolio[isin]:
        del portfolio[isin]["sell_date"]
        
    save_portfolio(portfolio)
    print(f"\n✅ KØB REGISTRERET: {name} ({isin}) til kurs {price}")

def sell(isin):
    portfolio = load_json(PORTFOLIO_FILE)
    if isin not in portfolio:
        print(f"\n❌ FEJL: Fonden {isin} findes ikke i din portefølje.")
        return

    portfolio[isin]["active"] = False
    portfolio[isin]["sell_date"] = datetime.now().strftime("%Y-%m-%d")
    
    save_portfolio(portfolio)
    print(f"\n⚠️ SALG REGISTRERET: {portfolio[isin]['name']} er nu markeret som solgt.")

if __name__ == "__main__":
    # Hvis man bare skriver 'python manage_portfolio.py' uden noget andet
    if len(sys.argv) < 3:
        show_help()
        sys.exit(0)

    command = sys.argv[1].lower()
    target_isin = sys.argv[2].upper()

    if command == "buy":
        if len(sys.argv) != 4:
            print("\n❌ FEJL: Du mangler at angive kursen.")
            show_help()
        else:
            try:
                buy(target_isin, sys.argv[3])
            except ValueError:
                print("\n❌ FEJL: Kursen skal være et tal (brug punktum).")
    elif command == "sell":
        sell(target_isin)
    else:
        print(f"\n❌ FEJL: Ukendt kommando '{command}'")
        show_help()
