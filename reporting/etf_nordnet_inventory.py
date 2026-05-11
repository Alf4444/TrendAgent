import requests
import json
from pathlib import Path
import time

# Stier konfigureret til dit etf_ setup
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data/etf_nordnet_inventory.json"

def fetch_nordnet_etfs():
    """Henter alle ETF'er fra Nordnet via deres opdaterede API endpoint."""
    
    # Nordnet bruger nu /list endpointet i stedet for /etf
    base_url = "https://www.nordnet.dk/api/2/instrument_search/query/list"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "da-DK,da;q=0.9",
        "Origin": "https://www.nordnet.dk",
        "Referer": "https://www.nordnet.dk/markedet/etf-lister"
    }

    all_etfs = {}
    limit = 100
    offset = 0

    print("🚀 Starter synkronisering med Nordnet (vha. /list endpoint)...")

    while True:
        # Vi definerer parametrene præcis som Nordnets egen web-app gør det
        params = {
            "sort_attribute": "acc_pct",
            "sort_order": "desc",
            "limit": limit,
            "offset": offset,
            "type": "etf",         # Dette fortæller API'et at vi kun vil have ETF'er
            "apply_filters": "true"
        }

        try:
            response = requests.get(base_url, params=params, headers=headers, timeout=15)
            
            if response.status_code != 200:
                print(f"❌ Fejl {response.status_code} ved offset {offset}. Stopper.")
                break
                
            data = response.json()
            
            # Nordnet pakker resultaterne ind i 'results'
            results = data.get("results", [])
            
            if not results:
                print(f"   ℹ️ Ingen flere resultater fundet ved offset {offset}.")
                break

            for item in results:
                # Vi kigger i 'instrument_info' hvis 'isin' ikke ligger i roden
                isin = item.get("isin") or item.get("instrument_info", {}).get("isin")
                name = item.get("name") or item.get("instrument_info", {}).get("name")
                inst_id = item.get("instrument_id")
                
                if isin and name:
                    all_etfs[isin] = {
                        "name": name,
                        "instrument_id": inst_id,
                        "symbol": item.get("symbol"),
                        "nordnet_url": f"https://www.nordnet.dk/markedet/etf-lister/{inst_id}" if inst_id else None
                    }
            
            print(f"   Hentet {len(all_etfs)} ETF'er...")
            
            # Hvis vi fik færre resultater end vores limit, er vi færdige
            if len(results) < limit:
                break
                
            offset += limit
            time.sleep(0.4) # Lille pause for at være høflig mod API'et

        except Exception as e:
            print(f"❌ Kritisk fejl: {e}")
            break

    # Gem til JSON
    if all_etfs:
        OUTPUT_FILE.parent.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_etfs, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Succes! Gemte {len(all_etfs)} unikke ETF'er til {OUTPUT_FILE.name}")
    else:
        print("\n❌ Listen er stadig tom. Noget gik galt med data-strukturen.")

if __name__ == "__main__":
    fetch_nordnet_etfs()
