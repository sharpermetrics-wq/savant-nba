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
st.set_page_config(page_title="Savant v5.7: Direct Injection", layout="wide")
st.title("🏀 Savant v5.7: NBB Direct Logic")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["Brazil NBB", "NBA", "EuroLeague"])
    
    league_map = {
        "Brazil NBB": {"len": 40, "coeff": 1.02},
        "NBA": {"len": 48, "coeff": 1.12},
        "EuroLeague": {"len": 40, "coeff": 0.94}
    }
    config = league_map[league_choice]

    st.divider()
    if st.button("🚀 FORCE SYNC NBB", type="primary"):
        st.rerun()

# --- STEP 1: THE "DIRECT" SCORE PULL ---
def get_nbb_live_scores():
    # We are targeting the specific raw JSON endpoint used by NBB trackers
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/brazil/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers).json()
        games = []
        for stage in res.get('Stages', []):
            for event in stage.get('Events', []):
                games.append({
                    "home": event['T1'][0]['Nm'],
                    "away": event['T2'][0]['Nm'],
                    "h_score": int(event.get('Tr1', 0) or 0),
                    "a_score": int(event.get('Tr2', 0) or 0),
                    "clock": str(event.get('Eps', '00:00'))
                })
        return games
    except: return []

# --- STEP 2: THE ENGINE ---
with st.spinner("Pinging Brazilian Data Centers..."):
    live_games = get_nbb_live_scores()
    results = []

    for game in live_games:
        total = game['h_score'] + game['a_score']
        clock = game['clock']
        
        # --- CLOCK PARSER ---
        try:
            if "'" in clock: mins = float(clock.replace("'", ""))
            elif ":" in clock:
                parts = clock.split(' ')
                q = int(parts[0].replace('Q','')) if 'Q' in parts[0] else 1
                m, s = map(int, parts[-1].split(':'))
                mins = ((q-1) * 10) + (10 - m - (s/60))
            elif "HT" in clock or "HALF" in clock: mins = 20.0
            else: mins = 10.0 # Default fallback
        except: mins = 10.0

        if mins > 0.5:
            proj = (total / mins) * config['len'] * config['coeff']
            results.append({
                "Game": f"{game['away']} @ {game['home']}",
                "Live Score": f"{game['a_score']} - {game['h_score']}",
                "Time Played": f"{round(mins, 1)}m",
                "Savant Proj": round(proj, 1)
            })

# --- DISPLAY ---
if results:
    st.table(pd.DataFrame(results))
    st.success("✅ Live NBB Data Captured!")
else:
    st.warning("No live games found at this exact second.")
    # DEBUG: Show EVERYTHING the API is returning
    with st.expander("🔍 System Debug: Raw Data Check"):
        st.write("API successfully pinged. Found games:", len(live_games))
        if live_games:
            st.write(live_games)
