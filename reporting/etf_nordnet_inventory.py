import requests
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data/nordnet_inventory.json"

def fetch_nordnet_etfs():
    """Henter alle ETF'er fra Nordnet via deres søge-API."""
    base_url = "https://www.nordnet.dk/api/2/instrument_search/query/etf"
    
    # Standard headers for at ligne en browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    all_etfs = {}
    limit = 100
    offset = 0
    total_found = 0

    print("🚀 Starter synkronisering med Nordnet...")

    while True:
        params = {
            "sort_attribute": "acc_pct",
            "sort_order": "desc",
            "limit": limit,
            "offset": offset
        }

        try:
            response = requests.get(base_url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                # Vi bruger ISIN som nøgle, da det er det mest stabile link
                isin = item.get("isin")
                if isin:
                    all_etfs[isin] = {
                        "name": item.get("name"),
                        "instrument_id": item.get("instrument_id"),
                        "symbol": item.get("symbol"),
                        "tradable": item.get("tradable", False),
                        "nordnet_url": f"https://www.nordnet.dk/markedet/etf-lister/{item.get('instrument_id')}-{item.get('name').replace(' ', '-').lower()}"
                    }
            
            total_found = len(all_etfs)
            print(f"   Hentet {total_found} ETF'er...")
            
            # Check om vi har nået bunden
            if len(results) < limit:
                break
                
            offset += limit
            time.sleep(0.5) # Høflighedspause

        except Exception as e:
            print(f"❌ Fejl ved hentning (offset {offset}): {e}")
            break

    # Gem til JSON
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_etfs, f, indent=2, ensure_ascii=False)

    print(f"✅ Færdig! Gemte {len(all_etfs)} unikke ISIN-koder til {OUTPUT_FILE.name}")

if __name__ == "__main__":
    fetch_nordnet_etfs()
