"""
=============================================================================
TRENDAGENT PORTFOLIO MANAGER
=============================================================================
Interaktiv menu til køb og salg af PFA-fonde.

Start med: python manage_portfolio.py
=============================================================================
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# STIER
ROOT           = Path(__file__).resolve().parent
PORTFOLIO_FILE = ROOT / "config" / "portfolio.json"
HWM_FILE       = ROOT / "data" / "high_water_marks.json"
LATEST_DATA    = ROOT / "data" / "latest.json"


# ==========================================
# FIL-HJÆLPEFUNKTIONER
# ==========================================

def load_json(path):
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception:
        return {}

def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_latest():
    """Returnerer dict: isin -> item fra latest.json"""
    latest = load_json(LATEST_DATA)
    if isinstance(latest, list):
        return {item['isin']: item for item in latest if 'isin' in item}
    return {}


# ==========================================
# SØGEFUNKTION
# ==========================================

def find_fund(query, latest_map):
    """
    Søger i portfolio + latest efter ISIN eller navn.
    Returnerer (isin, name, nav, currency) eller None.
    """
    query = query.strip().upper()
    portfolio = load_json(PORTFOLIO_FILE)

    # Samlet kandidatliste
    candidates = {}
    for isin, item in latest_map.items():
        candidates[isin] = {
            "name":     item.get('name', isin),
            "nav":      item.get('nav'),
            "currency": item.get('currency', 'DKK'),
        }
    for isin, p in portfolio.items():
        if isin not in candidates:
            candidates[isin] = {
                "name":     p.get('name', isin),
                "nav":      None,
                "currency": "DKK",
            }

    def pick(matches):
        if len(matches) == 1:
            isin = matches[0]
            c = candidates[isin]
            return isin, c['name'], c['nav'], c['currency']
        print(f"\n  Flere fund fundet:")
        for i, isin in enumerate(matches, 1):
            print(f"  {i}. {isin} — {candidates[isin]['name']}")
        try:
            choice = int(input("  Vælg nummer: ").strip())
            isin = matches[choice - 1]
            c = candidates[isin]
            return isin, c['name'], c['nav'], c['currency']
        except Exception:
            return None

    # Direkte ISIN-match
    if query in candidates:
        c = candidates[query]
        return query, c['name'], c['nav'], c['currency']

    # Delvist ISIN-match (fx "2732")
    isin_matches = [isin for isin in candidates if query in isin]
    if isin_matches:
        return pick(isin_matches)

    # Navnesøgning
    query_lower = query.lower()
    name_matches = [
        isin for isin, c in candidates.items()
        if query_lower in c['name'].lower()
    ]
    if name_matches:
        return pick(name_matches)

    return None


# ==========================================
# INPUT-HJÆLPEFUNKTIONER
# ==========================================

def ask_price(prompt, default=None):
    default_str = f" [Enter = {default}]" if default is not None else ""
    raw = input(f"  {prompt}{default_str}: ").strip().replace(",", ".")
    if not raw and default is not None:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        print("  ❌ Ugyldigt tal — brug punktum som decimaltegn (fx 415.21).")
        return ask_price(prompt, default)

def ask_date(prompt, default=None):
    today = datetime.now().strftime("%Y-%m-%d")
    default = default or today
    raw = input(f"  {prompt} [Enter = {default}]: ").strip()
    if not raw:
        return default
    try:
        datetime.strptime(raw, "%Y-%m-%d")
        return raw
    except ValueError:
        print("  ❌ Ugyldig dato — brug YYYY-MM-DD (fx 2026-05-02).")
        return ask_date(prompt, default)

def ask_isin(latest_map):
    query = input("  ISIN eller navn (del er nok): ").strip()
    if not query:
        return None
    result = find_fund(query, latest_map)
    if not result:
        print(f"  ❌ Ingen fond fundet for '{query}'.")
    return result


# ==========================================
# MENU-HANDLINGER
# ==========================================

def menu_buy(latest_map):
    print("\n── REGISTRER KØB ──────────────────────────")

    result = ask_isin(latest_map)
    if not result:
        return
    isin, name, nav, currency = result

    print(f"\n  Fundet:      {name}")
    print(f"  ISIN:        {isin}")
    if nav:
        print(f"  Aktuel kurs: {nav} {currency} (fra seneste PFA-data)")

    price = ask_price("Handelskurs", default=nav)
    date  = ask_date("Handelsdato")

    portfolio = load_json(PORTFOLIO_FILE)
    existing_name = portfolio.get(isin, {}).get('name') or name

    portfolio[isin] = {
        "name":      existing_name,
        "active":    True,
        "buy_date":  date,
        "buy_price": round(price, 4),
    }
    portfolio[isin].pop("sell_date",  None)
    portfolio[isin].pop("sell_price", None)
    save_json(PORTFOLIO_FILE, portfolio)

    # Nulstil HWM til ny handelskurs
    hwm = load_json(HWM_FILE)
    hwm[isin] = {"hwm": round(price, 4), "hwm_date": date}
    save_json(HWM_FILE, hwm)

    print(f"\n  ✅ KØB REGISTRERET")
    print(f"     Fond:  {existing_name} ({isin})")
    print(f"     Kurs:  {price} {currency}")
    print(f"     Dato:  {date}")
    print(f"     HWM nulstillet til {price} — Trail Stop starter herfra")


def menu_sell(latest_map):
    print("\n── REGISTRER SALG ─────────────────────────")

    portfolio = load_json(PORTFOLIO_FILE)
    active = {isin: p for isin, p in portfolio.items() if p.get('active')}
    if not active:
        print("  Ingen aktive positioner at sælge.")
        return

    print("\n  Aktive positioner:")
    for isin, p in active.items():
        nav = latest_map.get(isin, {}).get('nav')
        nav_str = f"  (aktuel: {nav})" if nav else ""
        buy_p = p.get('buy_price', 0)
        ret = f"  {((nav - buy_p) / buy_p * 100):+.1f}%" if nav and buy_p else ""
        print(f"  {isin} — {p['name']}{nav_str}{ret}")

    result = ask_isin(latest_map)
    if not result:
        return
    isin, name, nav, currency = result

    if isin not in active:
        print(f"  ❌ {name} er ikke en aktiv position.")
        return

    print(f"\n  Fundet:      {name}")
    print(f"  ISIN:        {isin}")
    print(f"  Købt til:    {portfolio[isin]['buy_price']} ({portfolio[isin]['buy_date']})")
    if nav:
        print(f"  Aktuel kurs: {nav} {currency} (fra seneste PFA-data)")

    price = ask_price("Salgskurs", default=nav)
    date  = ask_date("Salgsdato")

    buy_price = portfolio[isin].get('buy_price', 0)
    ret = round(((price - buy_price) / buy_price * 100), 2) if buy_price else 0

    portfolio[isin]["active"]     = False
    portfolio[isin]["sell_date"]  = date
    portfolio[isin]["sell_price"] = round(price, 4)
    save_json(PORTFOLIO_FILE, portfolio)

    print(f"\n  ✅ SALG REGISTRERET")
    print(f"     Fond:    {name} ({isin})")
    print(f"     Kurs:    {price} {currency}")
    print(f"     Dato:    {date}")
    print(f"     Afkast:  {ret:+.2f}% siden køb til {buy_price}")
    print(f"     ℹ️  HWM-historik bevares i high_water_marks.json")


def menu_update_price(latest_map):
    print("\n── OPDATER HANDELSKURS ────────────────────")
    print("  Brug dette når PFA bekræfter den reelle kurs 1-2 dage efter handel.\n")

    result = ask_isin(latest_map)
    if not result:
        return
    isin, name, nav, currency = result

    portfolio = load_json(PORTFOLIO_FILE)
    if isin not in portfolio:
        print(f"  ❌ {name} ({isin}) findes ikke i porteføljen.")
        return

    p = portfolio[isin]
    is_active = p.get('active', False)

    if is_active:
        current_price = p.get('buy_price')
        current_date  = p.get('buy_date')
        price_label   = "købskurs"
    else:
        current_price = p.get('sell_price')
        current_date  = p.get('sell_date')
        price_label   = "salgskurs"

    print(f"\n  Fundet:       {name} ({isin})")
    print(f"  Gemt {price_label}:  {current_price} ({current_date})")
    if nav:
        print(f"  Aktuel kurs:  {nav} {currency}")

    new_price = ask_price(f"Ny {price_label}", default=current_price)

    if new_price == current_price:
        print("  Ingen ændring — kurs er uændret.")
        return

    if is_active:
        portfolio[isin]["buy_price"] = round(new_price, 4)
        # Opdater HWM hvis den stadig er lig gammel købspris
        hwm = load_json(HWM_FILE)
        hwm_val = hwm.get(isin, {}).get('hwm', 0)
        if hwm_val == current_price:
            hwm[isin]['hwm'] = round(new_price, 4)
            save_json(HWM_FILE, hwm)
            print(f"  ℹ️  HWM opdateret fra {current_price} til {new_price}")
    else:
        portfolio[isin]["sell_price"] = round(new_price, 4)

    save_json(PORTFOLIO_FILE, portfolio)

    print(f"\n  ✅ KURS OPDATERET")
    print(f"     Fond:     {name}")
    print(f"     Gammel:   {current_price}")
    print(f"     Ny kurs:  {new_price}")
    print(f"     Dato:     {current_date} (handelsdato bevares uændret)")


def menu_show(latest_map):
    print("\n── POSITIONER ─────────────────────────────")
    portfolio = load_json(PORTFOLIO_FILE)

    if not portfolio:
        print("  Ingen positioner registreret.")
        return

    active = {k: v for k, v in portfolio.items() if v.get('active')}
    sold   = {k: v for k, v in portfolio.items() if not v.get('active')}

    if active:
        print(f"\n  ⭐ AKTIVE POSITIONER:")
        print(f"  {'ISIN':<16} {'Fond':<32} {'Købt':>8} {'Dato':<12} {'Aktuel':>8} {'Afkast':>8}")
        print("  " + "─" * 90)
        for isin, p in active.items():
            buy_p   = p.get('buy_price', 0)
            nav     = latest_map.get(isin, {}).get('nav')
            ret_str = f"{((nav - buy_p) / buy_p * 100):+.1f}%" if nav and buy_p else "–"
            nav_str = f"{nav:.2f}" if nav else "–"
            print(f"  {isin:<16} {p['name'][:32]:<32} {buy_p:>8.2f} {p.get('buy_date','–'):<12} {nav_str:>8} {ret_str:>8}")

    if sold:
        print(f"\n  ❌ SOLGTE POSITIONER:")
        print(f"  {'ISIN':<16} {'Fond':<32} {'Købt':>8} {'Solgt':>8} {'Afkast':>8}")
        print("  " + "─" * 78)
        for isin, p in sold.items():
            buy_p  = p.get('buy_price', 0)
            sell_p = p.get('sell_price', 0)
            ret_str = f"{((sell_p - buy_p) / buy_p * 100):+.1f}%" if buy_p and sell_p else "–"
            print(f"  {isin:<16} {p['name'][:32]:<32} {buy_p:>8.2f} {sell_p:>8.2f} {ret_str:>8}")

    print()


# ==========================================
# HOVEDMENU
# ==========================================

def main():
    latest_map = load_latest()

    while True:
        print("\n" + "="*45)
        print("🚀 TRENDAGENT PORTFOLIO MANAGER")
        print("="*45)
        print("  1. Registrer køb")
        print("  2. Registrer salg")
        print("  3. Opdater handelskurs (når PFA bekræfter)")
        print("  4. Vis positioner")
        print("  0. Afslut")
        print("─"*45)

        choice = input("Vælg: ").strip()

        if   choice == "1": menu_buy(latest_map)
        elif choice == "2": menu_sell(latest_map)
        elif choice == "3": menu_update_price(latest_map)
        elif choice == "4": menu_show(latest_map)
        elif choice == "0":
            print("\nFarvel! 👋\n")
            break
        else:
            print("  ❌ Ugyldigt valg — tast 0-4.")


if __name__ == "__main__":
    main()
