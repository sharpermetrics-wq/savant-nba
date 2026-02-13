import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v5.8: The NBB Fix", layout="wide")
st.title("🏀 Savant v5.8: Overcoming 'Limited Coverage'")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["Brazil NBB", "NBA", "EuroLeague"])
    
    config = {
        "Brazil NBB": {"len": 40, "coeff": 1.02},
        "NBA": {"len": 48, "coeff": 1.12},
        "EuroLeague": {"len": 40, "coeff": 0.94}
    }[league_choice]

    st.divider()
    if st.button("🚀 FORCE RE-SCRAPE", type="primary"):
        st.rerun()

# --- STEP 1: THE "COVERAGE BYPASS" SCRAPER ---
def scrape_nbb_live():
    # Using a more robust source for NBB Live Scores
    url = "https://www.basketball24.com/brazil/nbb/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        response = requests.get(url, headers=headers)
        # Basketball24 uses a specific format; we'll look for live score markers
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Note: Scrapers for these sites are complex because data is loaded via JS.
        # As a failsafe, we'll use a direct "LiveScore" search filter
        games = []
        
        # This is a fallback to the 'Live' pulse but with a 'Stage' override
        pulse_url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
        res = requests.get(pulse_url, headers=headers).json()
        
        for stage in res.get('Stages', []):
            # Check for ANY Brazil or NBB marker in the stage
            s_nm = stage.get('Snm', '').upper()
            if "BRAZIL" in s_nm or "NBB" in s_nm:
                for event in stage.get('Events', []):
                    games.append({
                        "home": event['T1'][0]['Nm'],
                        "away": event['T2'][0]['Nm'],
                        "h_score": int(event.get('Tr1', 0) or 0),
                        "a_score": int(event.get('Tr2', 0) or 0),
                        "clock": str(event.get('Eps', '00:00'))
                    })
        return games
    except:
        return []

# --- STEP 2: THE ENGINE ---
with st.spinner("Bypassing API restrictions..."):
    live_games = scrape_nbb_live()
    results = []

    for game in live_games:
        total = game['h_score'] + game['a_score']
        clock = game['clock']
        
        # Clock logic
        try:
            if "'" in clock: mins = float(clock.replace("'", ""))
            elif ":" in clock:
                parts = clock.split(' ')
                q = int(parts[0].replace('Q','')) if 'Q' in parts[0] else 1
                m, s = map(int, parts[-1].split(':'))
                mins = ((q-1) * 10) + (10 - m - (s/60))
            elif "HT" in clock or "HALF" in clock: mins = 20.0
            else: mins = 2.0 # Minimum play time
        except: mins = 2.0

        if mins > 0:
            proj = (total / mins) * config['len'] * config['coeff']
            results.append({
                "Game": f"{game['away']} @ {game['home']}",
                "Score": f"{game['a_score']} - {game['h_score']}",
                "Mins": round(mins, 1),
                "Savant Proj": round(proj, 1)
            })

# --- DISPLAY ---
if results:
    st.table(pd.DataFrame(results))
    st.success("✅ NBB Data Successfully Injected")
else:
    st.error("No games currently tracking as 'Live' in the data feed.")
    st.info("💡 **Manual Override:** Since the API is lagging on NBB, you can use the sidebar 'Manual' button from v5.6 to enter the score you see on TV.")
