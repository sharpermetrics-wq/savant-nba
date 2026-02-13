import streamlit as st
import pandas as pd
import requests
from apify_client import ApifyClient

# --- SECURE CONFIG ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("Please set APIFY_TOKEN in Streamlit Secrets.")
    st.stop()

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v5.1", layout="wide")
st.title("🏀 Savant Global: Multi-Source Automation")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "Brazil NBB", "CBA (China)"])
    
    league_map = {
        "NBA": {"apify_id": "harvest/sportsbook-odds-scraper", "league_val": "NBA", "len": 48, "coeff": 1.12},
        "EuroLeague": {"apify_id": "harvest/sportsbook-odds-scraper", "league_val": "UCL", "len": 40, "coeff": 0.94},
        "Brazil NBB": {"apify_id": "tropical_quince/sports-odds-scraper", "league_val": "basketball", "len": 40, "coeff": 1.02},
        "CBA (China)": {"apify_id": "tropical_quince/sports-odds-scraper", "league_val": "basketball", "len": 40, "coeff": 1.05}
    }
    config = league_map[league_choice]

    if st.button("🚀 FULL AUTO-SCAN", type="primary"):
        st.rerun()

# --- STEP 1: DYNAMIC ODD SCRAPING ---
def get_automated_odds(config_item):
    client = ApifyClient(APIFY_TOKEN)
    actor_id = config_item['apify_id']
    
    # Different scrapers require different input formats
    if "harvest" in actor_id:
        run_input = {"league": config_item['league_val'], "sportsbook": "FanDuel"}
    else:
        # Global scraper for NBB/CBA
        run_input = {"sport": config_item['league_val'], "maxEvents": 50}
    
    try:
        run = client.actor(actor_id).call(run_input=run_input)
        odds_map = {}
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            # Standardize names across different scraper outputs
            home = item.get('homeTeam', item.get('home_team', ''))
            # Some actors return 'overUnder', some return 'total'
            line = item.get('overUnder', item.get('total_line', 0))
            if home and line:
                odds_map[home] = line
        return odds_map
    except Exception as e:
        st.error(f"Scraper Error: {e}")
        return {}

# --- STEP 2: REAL-TIME CLOCK SCRAPER ---
def get_precision_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers).json()
        score_data = {}
        if isinstance(res, dict) and 'Stages' in res:
            for stage in res['Stages']:
                for event in stage.get('Events', []):
                    home = event.get('T1', [{}])[0].get('Nm', 'Unknown')
                    score_data[home] = {
                        "h_score": int(event.get('Tr1', 0)) if event.get('Tr1') else 0,
                        "a_score": int(event.get('Tr2', 0)) if event.get('Tr2') else 0,
                        "clock": str(event.get('Eps', '00:00'))
                    }
        return score_data
    except: return {}

# --- STEP 3: EXECUTION ---
with st.spinner(f"Scanning {league_choice}..."):
    odds_data = get_automated_odds(config)
    live_data = get_precision_scores()
    
    results = []
    for team, line in odds_data.items():
        match = next((v for k, v in live_data.items() if team in k or k in team), None)
        if match:
            # [Insert Savant Math logic here: Time -> Projection -> Edge]
            curr_total = match['h_score'] + match['a_score']
            # Simple clock parser
            try:
                if "'" in match['clock']: mins = float(match['clock'].replace("'", ""))
                else: mins = 20 # Default to half for testing if clock fails
            except: mins = 20
            
            proj = (curr_total / mins) * config['len'] * config['coeff']
            edge = round(proj - line, 1)
            
            results.append({"Team": team, "Score": f"{match['a_score']}-{match['h_score']}", "Proj": round(proj, 1), "Line": line, "EDGE": edge})

if results:
    st.dataframe(pd.DataFrame(results))
else:
    st.info("No matching live games found. Tip: Check the names on LiveScore vs FanDuel.")
