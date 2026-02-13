import streamlit as st
import pandas as pd
import requests
from apify_client import ApifyClient

# --- SECURE CONFIG ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("Missing APIFY_TOKEN in Streamlit Secrets! (Dashboard -> Settings -> Secrets)")
    st.stop()

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v5.4: Global HUD", page_icon="🏀", layout="wide")
st.title("🏀 Savant Global v5.4: Zero-Barrier Build")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "Brazil NBB", "CBA (China)"])
    
    league_map = {
        "NBA": {"mode": "direct", "val": "NBA", "len": 48, "coeff": 1.12},
        "EuroLeague": {"mode": "direct", "val": "UCL", "len": 40, "coeff": 0.94},
        "Brazil NBB": {"mode": "manual", "val": "Brazil", "len": 40, "coeff": 1.02},
        "CBA (China)": {"mode": "manual", "val": "China", "len": 40, "coeff": 1.05}
    }
    config = league_map[league_choice]

    st.divider()
    st.header("⚙️ Execution")
    if st.button("🚀 FULL SYNC SCAN", type="primary"):
        st.rerun()

# --- STEP 1: SMART ODDS SCRAPER ---
def get_automated_odds(config_item):
    if config_item['mode'] == "manual":
        return {} # Skip API for leagues we know are restricted
        
    client = ApifyClient(APIFY_TOKEN)
    try:
        run_input = {"league": config_item['val'], "sportsbook": "FanDuel"}
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input=run_input)
        
        odds_map = {}
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            home = item.get('homeTeam', '')
            for odd in item.get('odds', []):
                if odd.get('type') == 'overUnder':
                    odds_map[home] = odd.get('overUnder', 0)
        return odds_map
    except:
        return {}

# --- STEP 2: REAL-TIME SCORE PULSE ---
def get_precision_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        score_data = []
        if isinstance(res, dict) and 'Stages' in res:
            for stage in res['Stages']:
                league_nm = stage.get('Snm', '')
                for event in stage.get('Events', []):
                    home = event.get('T1', [{}])[0].get('Nm', 'Unknown')
                    score_data.append({
                        "home": home,
                        "h_score": int(event.get('Tr1', 0)) if event.get('Tr1') else 0,
                        "a_score": int(event.get('Tr2', 0)) if event.get('Tr2') else 0,
                        "clock": str(event.get('Eps', '00:00')),
                        "league": league_nm
                    })
        return score_data
    except: return []

# --- STEP 3: THE ENGINE ---
with st.spinner(f"Synchronizing {league_choice} Pulse..."):
    odds_data = get_automated_odds(config)
    live_data = get_precision_scores()
    
    results = []
    
    for game in live_data:
        # BROAD MATCHING: Check if the league or team contains our target keyword
        is_target_league = (config['val'].lower() in game['league'].lower()) or \
                          (league_choice == "Brazil NBB" and "NBB" in game['league'])
        
        if is_target_league:
            curr_total = game['h_score'] + game['a_score']
            clock = game['clock']
            
            # --- PRECISION CLOCK PARSER ---
            try:
                if "'" in clock: 
                    mins = float(clock.replace("'", ""))
                elif ":" in clock:
                    parts = clock.split(' ')
                    q = int(parts[0].replace('Q','')) if 'Q' in parts[0] else 1
                    time_part = parts[-1]
                    m, s = map(int, time_part.split(':'))
                    q_len = config['len'] / 4
                    mins = ((q-1) * q_len) + (q_len - m - (s/60))
                else: 
                    mins = 10 # Default to end of Q1
            except: mins = 10

            if mins > 1:
                # Core Savant Math
                ppm = curr_total / mins
                proj = curr_total + (ppm * (config['len'] - mins) * config['coeff'])
                
                # Match against Scraped Odds if available
                line = odds_data.get(game['home'], 0)
                display_line = line if line > 0 else "---"
                edge = round(proj - line, 1) if line > 0 else "N/A"

                results.append({
                    "Matchup": game['home'],
                    "Score": f"{game['a_score']}-{game['h_score']}",
                    "Clock": clock,
                    "Savant Proj": round(proj, 1),
                    "FanDuel Line": display_line,
                    "EDGE": edge
                })

# --- DISPLAY ---
if results:
    st.write(f"### Live {league_choice} Tracking")
    df = pd.DataFrame(results)
    
    # Using Table for high-visibility on Pixel 9 Pro
    st.table(df)
    
    if config['mode'] == "manual":
        st.info("💡 **NBB/CBA Mode:** FanDuel lines are hidden by API. Compare the 'Savant Proj' to the live total on your FanDuel app to find the edge.")
else:
    st.warning(f"No live {league_choice} games found. (Note: CBA is on break until Feb 25).")
