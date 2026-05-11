import requests
import json
from pathlib import Path
import time

# Vi sikrer os at stierne passer til dit nye filnavn
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data/etf_nordnet_inventory.json"

def fetch_nordnet_etfs():
    """Henter alle ETF'er fra Nordnet via deres søge-API."""
    # Vi bruger det fulde søge-endpoint som ofte er mere stabilt
    base_url = "https://www.nordnet.dk/api/2/instrument_search/query/etf"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "da-DK,da;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    all_etfs = {}
    limit = 100
    offset = 0

    print("🚀 Starter synkronisering med Nordnet...")

    while True:
        # Vi tilføjer 'apply_filters', da det tvinger API'et til at returnere de faktiske lister
        params = {
            "sort_attribute": "acc_pct",
            "sort_order": "desc",
            "limit": limit,
            "offset": offset,
            "apply_filters": "true"
        }

        try:
            response = requests.get(base_url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()

            # Nordnet pakker nogle gange data ind i 'results' eller 'instruments'
            # Vi tjekker begge steder
            results = data.get("results", data.get("instruments", []))
            
            if not results:
                print(f"   ⚠️ Ingen flere resultater fundet ved offset {offset}.")
                break

            for item in results:
                # Nogle gange ligger data i et 'main_market_price' eller 'instrument_info' objekt
                # Vi prøver at trække ISIN ud direkte
                isin = item.get("isin")
                name = item.get("name")
                
                if isin and name:
                    all_etfs[isin] = {
                        "name": name,
                        "instrument_id": item.get("instrument_id"),
                        "symbol": item.get("symbol"),
                        "tradable": item.get("tradable", False),
                        "nordnet_url": f"https://www.nordnet.dk/markedet/etf-lister/{item.get('instrument_id')}"
                    }
            
            print(f"   Hentet {len(all_etfs)} ETF'er indtil videre...")
            
            if len(results) < limit:
                break
                
            offset += limit
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ Fejl ved hentning (offset {offset}): {e}")
            break

    # Gem til JSON (kun hvis vi rent faktisk fandt noget)
    if all_etfs:
        OUTPUT_FILE.parent.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_etfs, f, indent=2, ensure_ascii=False)
        print(f"✅ Succes! Gemte {len(all_etfs)} unikke ISIN-koder til {OUTPUT_FILE.name}")
    else:
        print("❌ Fejl: Listen er stadig tom. Vi fik intet data fra Nordnet.")

if __name__ == "__main__":
    fetch_nordnet_etfs()
