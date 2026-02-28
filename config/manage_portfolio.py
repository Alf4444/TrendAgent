import json
import sys
from pathlib import Path
from datetime import datetime

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT = Path(__file__).resolve().parent
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
LATEST_DATA = ROOT / "data/latest.json"

def load_json(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_portfolio(data):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_fund_name(isin):
    """Henter navnet fra latest.json hvis fonden er ny."""
    latest = load_json(LATEST_DATA)
    # latest er en liste af dicts
    for item in latest:
        if item.get('isin') == isin:
            return item.get('name', isin)
    return isin

def buy(isin, price):
    portfolio = load_json(PORTFOLIO_FILE)
    name = portfolio.get(isin, {}).get('name') or get_fund_name(isin)
    
    portfolio[isin] = {
        "name": name,
        "active": True,
        "buy_date": datetime.now().strftime("%Y-%m-%d"),
        "buy_price": float(price)
    }
    
    # Fjern sell_date hvis den eksisterede fra tidligere handel
    if "sell_date" in portfolio[isin]:
        del portfolio[isin]["sell_date"]
        
    save_portfolio(portfolio)
    print(f"✅ KØB REGISTRERET: {name} ({isin}) til kurs {price}")

def sell(isin):
    portfolio = load_json(PORTFOLIO_FILE)
    if isin not in portfolio:
        print(f"❌ FEJL: Fonden {isin} findes ikke i din portefølje.")
        return

    portfolio[isin]["active"] = False
    portfolio[isin]["sell_date"] = datetime.now().strftime("%Y-%m-%d")
    
    save_portfolio(portfolio)
    print(f"⚠️ SALG REGISTRERET: {portfolio[isin]['name']} er nu sat som inaktiv.")

def show_usage():
    print("\n📈 TrendAgent Portefølje Styring")
    print("-" * 30)
    print("Brug:")
    print("  python manage_portfolio.py buy [ISIN] [PRIS]")
    print("  python manage_portfolio.py sell [ISIN]")
    print("\nEksempel:")
    print("  python manage_portfolio.py buy PFA000002703 415.21")
    print("-" * 30)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        show_usage()
        sys.exit(1)

    command = sys.argv[1].lower()
    target_isin = sys.argv[2].upper()

    if command == "buy":
        if len(sys.argv) != 4:
            print("❌ FEJL: Du skal angive en pris ved køb.")
        else:
            buy(target_isin, sys.argv[3])
    elif command == "sell":
        sell(target_isin)
    else:
        print(f"❌ FEJL: Ukendt kommando '{command}'")
        show_usage()
