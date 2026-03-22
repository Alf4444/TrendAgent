import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/weekly.html.j2"
REPORT_FILE = ROOT / "build/weekly.html"

# ==========================================
# TEKNISKE HJÆLPEFUNKTIONER
# ==========================================

def get_ma(prices, window):
    """Beregner Simple Moving Average (SMA)."""
    if not isinstance(prices, list) or len(prices) < window:
        return None
    # Tag de sidste 'window' priser og fjern None-værdier
    relevant = [p for p in prices[-window:] if p is not None]
    if len(relevant) < window:
        return None
    return sum(relevant) / window

def get_rsi(prices, window=14):
    """Beregner Relative Strength Index (RSI)."""
    if not isinstance(prices, list) or len(prices) <= window:
        return None
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    recent_deltas = deltas[-window:]
    
    gains = [d if d > 0 else 0 for d in recent_deltas]
    losses = [abs(d) if d < 0 else 0 for d in recent_deltas]
    
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ytd(prices_dict):
    """Beregner afkast siden årets start (Year-To-Date)."""
    if not prices_dict:
        return 0.0
    
    dates = sorted(prices_dict.keys())
    cur_year = datetime.now().year
    start_price = None
    
    # Find slut-kursen fra sidste år (31. dec eller tætteste før)
    for d in reversed(dates):
        if d < f"{cur_year}-01-01":
            start_price = prices_dict[d]
            break
            
    # Backup: Hvis vi ikke har data fra sidste år, brug første kurs i år
    if start_price is None:
        for d in dates:
            if d.startswith(str(cur_year)):
                start_price = prices_dict[d]
                break
                
    if not start_price or start_price == 0:
        return 0.0
        
    current_price = prices_dict[dates[-1]]
    return ((current_price / start_price) - 1) * 100

def calculate_drawdown(prices_list):
    """Beregner aktuel drawdown fra All-Time High i historikken."""
    if not prices_list:
        return 0.0
    
    ath = max(prices_list)
    if ath == 0:
        return 0.0
        
    current = prices_list[-1]
    return ((current / ath) - 1) * 100

# ==========================================
# HOVEDFUNKTION
# ==========================================

def build_weekly():
    print("🔄 Starter generering af ugerapport...")
    
    # Validering af filer
    for f in [HISTORY_FILE, LATEST_FILE, PORTFOLIO_FILE, TEMPLATE_FILE]:
        if not f.exists():
            print(f"❌ FEJL: Mangler fil: {f}")
            return

    # Indlæs data
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        history = json.load(f)
    with open(LATEST_FILE, 'r', encoding='utf-8') as f:
        latest = json.load(f)
    with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        p_data = json.load(f)
        # Vi antager 'active_holdings' indeholder ISIN koder
        portfolio_isins = p_data.get("active_holdings", [])

    rows = []
    active_returns = []
    
    for item in latest:
        isin = item['isin']
        p_dict = history.get(isin, {})
        s_dates = sorted(p_dict.keys())
        p_list = [p_dict[d] for d in s_dates]
        
        if not p_list:
            continue

        # Tekniske beregninger
        ma200 = get_ma(p_list, 200)
        cur_nav = item.get('nav', 0)
        
        # Momentum (Afstand til MA200 i %)
        # Vi bruger 0.0 som default hvis MA200 ikke kan beregnes endnu
        momentum = ((cur_nav / ma200) - 1) * 100 if ma200 else 0.0
        
        # Trend State (Skal være 'UP' eller 'DOWN' til templaten)
        trend_state = "UP" if momentum > 0 else "DOWN"
        
        # Nøgletal til ugerapporten
        ytd = calculate_ytd(p_dict)
        dd = calculate_drawdown(p_list)
        rsi = get_rsi(p_list, 14)
        
        # Total afkast (Proxy: Fra start af den tilgængelige historik)
        total_ret = ((cur_nav / p_list[0]) - 1) * 100 if p_list else 0.0
        
        is_active = isin in portfolio_isins
        week_change = item.get('return_1w', 0) or 0.0
        
        if is_active:
            active_returns.append(week_change)

        rows.append({
            'isin': isin,
            'name': item['name'],
            'week_change_pct': float(week_change),
            'total_return': float(total_ret),
            'trend_state': trend_state,
            'momentum': round(momentum, 2),
            'ytd_return': float(ytd),
            'drawdown': float(dd),
            'is_active': is_active,
            'rsi': rsi
        })

    # Aggregerede data
    # Sikkerhed mod DivisionByZero
    avg_portfolio_return = sum(active_returns) / len(active_returns) if active_returns else 0.0
    
    # Data til momentum-grafen (Top 10)
    chart_data = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]
    
    # Template Rendering
    template_text = TEMPLATE_FILE.read_text(encoding="utf-8")
    jinja_template = Template(template_text)
    
    # Vi bruger 'færdig_html' for at matche log-filerne
    færdig_html = jinja_template.render(
        week_number=datetime.now().isocalendar()[1],
        report_date=datetime.now().strftime("%d. %B %Y"),
        avg_portfolio_return=avg_portfolio_return,
        # Alarmer hvis en aktiv fond falder mere end 3%
        portfolio_alerts=[{'msg': '⚠️ Kraftigt fald i', 'name': r['name']} for r in rows if r['is_active'] and r['week_change_pct'] < -3.0],
        # Muligheder: Ikke ejet, positiv momentum og BULL trend
        market_opportunities=[r for r in rows if not r['is_active'] and r['momentum'] > 2.0 and r['trend_state'] == "UP"][:8],
        top_up=sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down=sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        # Sorter tabel: Aktive først, derefter momentum
        rows=sorted(rows, key=lambda x: (not x['is_active'], -x['momentum'])),
        chart_labels=[r['name'][:20] for r in chart_data],
        chart_values=[r['momentum'] for r in chart_data]
    )

    # Gem den færdige rapport
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(færdig_html, encoding="utf-8")
    
    print(f"✅ Succes! Ugerapport genereret: {REPORT_FILE}")

if __name__ == "__main__":
    build_weekly()
