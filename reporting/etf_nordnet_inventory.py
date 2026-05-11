import requests
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data/etf_nordnet_inventory.json"

def fetch_nordnet_etfs():
    # Dette er det ENESTE endpoint der virker i dag
    url = "https://www.nordnet.dk/api/2/instrument_search/query/list"
    
    # Nordnet kræver disse headers for ikke at give 403 eller 404
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.nordnet.dk/markedet/etf-lister",
        "client-id": "NEXT" # Meget vigtig parameter
    }

    all_etfs = {}
    limit = 100
    offset = 0

    print(f"🚀 Forbinder til Nordnet API...")

    while True:
        # Vi skal definere 'type' og 'free_text' eller filtre for at få svar
        params = {
            "type": "etf",
            "limit": limit,
            "offset": offset,
            "sort_attribute": "yield_1y",
            "sort_order": "desc",
            "apply_filters": "true"
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            
            if response.status_code != 200:
                print(f"❌ STOP: API svarede med fejl {response.status_code}")
                break

            data = response.json()
            results = data.get("results", [])

            if not results:
                break

            for item in results:
                # Nordnet gemmer ofte isin inde i et 'instrument_info' objekt nu
                info = item.get("instrument_info", item)
                isin = info.get("isin")
                
                if isin:
                    all_etfs[isin] = {
                        "name": info.get("name"),
                        "instrument_id": item.get("instrument_id"),
                        "symbol": info.get("symbol"),
                        "tradable": item.get("tradable", True)
                    }

            print(f"   Hentet {len(all_etfs)} ETF'er...")
            
            if len(results) < limit:
                break
            
            offset += limit
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ Fejl: {e}")
            break

    if all_etfs:
        OUTPUT_FILE.parent.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_etfs, f, indent=2, ensure_ascii=False)
        print(f"✅ Succes: Gemte {len(all_etfs)} ETF'er i {OUTPUT_FILE.name}")
    else:
        print("❌ Listen er tom. Tjek venligst dine headers eller API endpoint.")

if __name__ == "__main__":
    fetch_nordnet_etfs()
