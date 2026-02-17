# parser/parse_pfa.py
import argparse, csv, io, json, os, requests
from datetime import date

def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def load_funds(path="data/funds.csv"):
    rows=[]
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["isin"] and r["source_url"]:
                rows.append(r)
    return rows

def build_mock_latest(funds):
    base=100.0
    out=[]
    for i,f in enumerate(funds):
        out.append({
            "isin": f["isin"],
            "nav": round(base+i*0.37,2),
            "nav_date": date.today().isoformat(),
            "change_pct": 0.0,
            "trend_shift": False,
            "cross_20_50": False,
            "trend_state": "NEUTRAL",
            "week_change_pct": 0.0,
            "ytd_return": 0.0,
            "drawdown": 0.0
        })
    return out

def build_real_latest(funds):
    # HER indsætter vi kun den ENKLE NAV-udtrækning
    # Ud fra dine parse-debug-filer ved vi:
    # - "Indre værdi" = første linje efter 4. label
    # - "Indre værdi dato" = næste linje
    import pdfminer.high_level

    def get_nav_and_date(pdf_bytes):
        text = pdfminer.high_level.extract_text(io.BytesIO(pdf_bytes))
        lines=[l.strip() for l in text.splitlines() if l.strip()]

        # Find "Stamdata"
        try:
            si = lines.index("Stamdata")
        except:
            return None, None

        # De næste 6 labels er faste:
        # Opstart, Valuta, Type, Indre værdi, Indre værdi dato, Bæredygtighed
        # De næste 6 linjer er værdier i samme rækkefølge.
        vals = lines[si+7:si+13]
        if len(vals)<6:
            return None,None

        # Indre værdi = værdi[3]
        # Indre værdi dato = værdi[4]
        nav_raw = vals[3].replace(".", "").replace(",", ".")
        try: nav=float(nav_raw)
        except: nav=None

        date_raw = vals[4]
        try:
            d,m,y = date_raw.split("-")
            nav_date = f"{y}-{m}-{d}"
        except:
            nav_date=None

        return nav, nav_date

    out=[]
    for f in funds:
        try:
            r=requests.get(f["source_url"], timeout=20)
            if r.status_code!=200:
                out.append({"isin":f["isin"],"nav":None,"nav_date":None,
                            "change_pct":None,"trend_shift":False,
                            "cross_20_50":False,"trend_state":"NEUTRAL",
                            "week_change_pct":None,"ytd_return":None,
                            "drawdown":None})
                continue
            nav,nav_date=get_nav_and_date(r.content)
        except:
            nav,nav_date=None,None

        out.append({
            "isin":f["isin"],"nav":nav,"nav_date":nav_date,
            "change_pct":None,"trend_shift":False,"cross_20_50":False,
            "trend_state":"NEUTRAL",
            "week_change_pct":None,"ytd_return":None,"drawdown":None
        })
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="latest.json")
    ap.add_argument("--mock",action="store_true")
    args=ap.parse_args()

    funds=load_funds()

    if args.mock:
        rows=build_mock_latest(funds)
    else:
        rows=build_real_latest(funds)

    with open(args.out,"w",encoding="utf-8") as f:
        json.dump({"rows":rows,"run_date":date.today().isoformat()},f,indent=2,ensure_ascii=False)

if __name__=="__main__":
    main()
