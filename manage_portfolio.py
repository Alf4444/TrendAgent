import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
PORTFOLIO_FILE = ROOT / "config" / "portfolio.json"
LATEST_DATA = ROOT / "data" / "latest.json"

def load_json(path):
    if not path.exists(): return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_portfolio(data):
    PORTFOLIO_FILE.parent.mkdir(exist_ok=True)
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_fund_name(isin):
    latest = load_json(LATEST_DATA)
    if isinstance(latest, list):
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
    if "sell_date" in portfolio[isin]: del portfolio[isin]["sell_date"]
    save_portfolio(portfolio)
    print(f"\n✅ KØB REGISTRERET: {name} til kurs {price}")

def sell(isin):
    portfolio = load_json(PORTFOLIO_FILE)
    if isin not in portfolio:
        print(f"\n❌ FEJL: Fonden {isin} ikke fundet.")
        return
    portfolio[isin]["active"] = False
    portfolio[isin]["sell_date"] = datetime.now().strftime("%Y-%m-%d")
    save_portfolio(portfolio)
    print(f"\n⚠️ SALG REGISTRERET: {portfolio[isin]['name']} er nu inaktiv.")

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(1)
    command = sys.argv[1].lower()
    target_isin = sys.argv[2].upper()
    if command == "buy" and len(sys.argv) == 4:
        buy(target_isin, sys.argv[3])
    elif command == "sell":
        sell(target_isin)