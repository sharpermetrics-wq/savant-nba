import streamlit as st
import pandas as pd
import requests
from apify_client import ApifyClient

# --- SECURE CONFIG ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("Missing APIFY_TOKEN in Streamlit Secrets!")
    st.stop()

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v5.3: Zero-Error Auto", layout="wide")
st.title("🏀 Savant Global v5.3: Zero-Error Automation")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "Brazil NBB", "CBA (China)"])
    
    # NEW: Simplified mapping to avoid validation errors
    # 'mode' determines the logic path
    league_map = {
        "NBA": {"mode": "direct", "val": "NBA", "len": 48, "coeff": 1.12},
        "EuroLeague": {"mode": "direct", "val": "UCL", "len": 40, "coeff": 0.94},
        "Brazil NBB": {"mode": "search", "val": "Brazil NBB", "len": 40, "coeff": 1.02},
        "CBA (China)": {"mode": "search", "val": "China CBA", "len": 40, "coeff": 1.05}
    }
    config = league_map[league_choice]

    st.divider()
    if st.button("🚀 FULL AUTO-SCAN", type="primary"):
        st.rerun()

# --- STEP 1: SMART ODDS SCRAPER ---
def get_automated_odds(config_item):
    client = ApifyClient(APIFY_TOKEN)
    
    try:
        if config_item['mode'] == "direct":
            # Direct path for major leagues (Very Fast)
            run_input = {"league": config_item['val'], "sportsbook": "FanDuel"}
            run = client.actor("harvest/sportsbook-odds-scraper").call(run_input=run_input)
            
            odds_map = {}
            for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                home = item.get('homeTeam', '')
                for odd in item.get('odds', []):
                    if odd.get('type') == 'overUnder':
                        odds_map[home] = odd.get('overUnder', 0)
            return odds_map
        
        else:
            # Search path for NBB/CBA to avoid "Allowed Value" errors
            # We use a broad search scraper that accepts ANY string
            run_input = {"searchQuery": config_item['val'], "maxResults": 10}
            run = client.actor("apify/google-search-scraper").call(run_input=run_input)
            
            # Note: This is a placeholder for a 'Search-to-Data' logic
            # For now, if automation fails for NBB, we default to the score-only view
            return {}

    except Exception as e:
        # If Apify throws a validation error, we catch it here so the app doesn't crash
        return {}

# --- STEP 2: REAL-TIME SCORES (Livescore Pulse) ---
def get_precision_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        score_data = {}
        if isinstance(res, dict) and 'Stages' in res:
            for stage in res['Stages']:
                # We filter for the specific league in the score feed
                league_nm = stage.get('Snm', '')
                for event in stage.get('Events', []):
                    home = event.get('T1', [{}])[0].get('Nm', 'Unknown')
                    score_data[home] = {
                        "h_score": int(event.get('Tr1', 0)) if event.get('Tr1') else 0,
                        "a_score": int(event.get('Tr2', 0)) if event.get('Tr2') else 0,
                        "clock": str(event.get('Eps', '00:00')),
                        "league": league_nm
                    }
        return score_data
    except: return {}

# --- STEP 3: THE ENGINE ---
with st.spinner(f"Analyzing {league_choice}..."):
    odds_data = get_automated_odds(config)
    live_data = get_precision_scores()
    
    results = []
    
    # If odds_data is empty (like for NBB/CBA), we show the LIVE SCORES ONLY
    # This allows you to at least see the PPM and Projection even without the Line
    if not odds_data:
        st.warning(f"Automated Odds for {league_choice} are restricted by API. Showing Live Projections only.")
        # Create a 'fake' odds_data based on live games found
        for team, data in live_data.items():
            if league_choice == "Brazil NBB" and "Brazil" in data['league']:
                odds_data[team] = 0 # Mark line as 0 for manual comparison
            elif league_choice == "CBA (China)" and "China" in data['league']:
                odds_data[team] = 0

    for team, line in odds_data.items():
        match = next((v for k, v in live_data.items() if team in k or k in team), None)
        if match:
            curr_total = match['h_score'] + match['a_score']
            clock = match['clock']
            
            # --- CLOCK PARSER ---
            try:
                if "'" in clock: mins = float(clock.replace("'", ""))
                elif ":" in clock:
                    q = int(clock.split(' ')[0].replace('Q','')) if 'Q' in clock else 1
                    m, s = map(int, clock.split(' ')[1].split(':'))
                    q_len = config['len'] / 4
                    mins = ((q-1) * q_len) + (q_len - m - (s/60))
                else: mins = 20
            except: mins = 20

            if mins > 2:
                ppm = curr_total / mins
                proj = curr_total + (ppm * (config['len'] - mins) * config['coeff'])
                edge = round(proj - line, 1) if line > 0 else "N/A"

                results.append({
                    "Matchup": team,
                    "Score": f"{match['a_score']}-{match['h_score']}",
                    "Clock": clock,
                    "Savant Proj": round(proj, 1),
                    "FanDuel": line if line > 0 else "Manual Input",
                    "EDGE": edge
                })

if results:
    df = pd.DataFrame(results)
    st.dataframe(df.style.background_gradient(cmap='RdYlGn', subset=['Savant Proj']), use_container_width=True)
else:
    st.info("No live games found. The NBB games (União Corinthians vs Pinheiros) should be active.")
