import streamlit as st
import pandas as pd
import requests
from apify_client import ApifyClient

# --- CONFIGURATION ---
# Pulling the key from your Streamlit "Secrets" vault
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except KeyError:
    st.error("Missing APIFY_TOKEN in Streamlit Secrets! Check your dashboard settings.")
    st.stop()

FANDUEL_URL = "https://sportsbook.fanduel.com/navigation/basketball"

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v5: Pro HUD", page_icon="🏀", layout="wide")
st.title("🏀 Savant Global v5: Automation Build")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("Choose League", ["NBA", "EuroLeague", "Brazil NBB", "CBA (China)"])
    
    # League Specific Mappings for Logic
    league_map = {
        "NBA": {"odds_key": "NBA", "len": 48, "coeff": 1.12},
        "EuroLeague": {"odds_key": "EuroLeague", "len": 40, "coeff": 0.94},
        "Brazil NBB": {"odds_key": "Brazil-NBB", "len": 40, "coeff": 1.02},
        "CBA (China)": {"odds_key": "CBA", "len": 40, "coeff": 1.05}
    }
    config = league_map[league_choice]

    st.divider()
    st.header("⚙️ Execution")
    min_edge = st.slider("Min EDGE Trigger", 2.0, 10.0, 4.0)
    
    if st.button("🚀 FULL AUTO-SCAN", type="primary"):
        st.rerun()

# --- STEP 1: PULL LIVE ODDS (APIFY) ---
def get_automated_odds(league_name):
    client = ApifyClient(APIFY_TOKEN)
    
    # Selecting the best source based on the league
    # CBA and NBB often require Bet365/BetMGM for live lines
    source_book = "FanDuel" if league_name in ["NBA", "EuroLeague"] else "Bet365"
    
    run_input = {
        "league": league_name,
        "sportsbook": source_book
    }
    
    try:
        # Calling the community-maintained sportsbook scraper
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input=run_input)
        odds_map = {}
        
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            home = item.get('homeTeam', '')
            for odd in item.get('odds', []):
                if odd.get('type') == 'overUnder':
                    odds_map[home] = odd.get('overUnder', 0)
        return odds_map
    except Exception as e:
        st.warning(f"Apify Scraper delay or error: {e}")
        return {}

# --- STEP 2: PULL REAL-TIME SCORES & CLOCK ---
def get_precision_scores():
    # Scraping the high-speed JSON pulse from LiveScore.com
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
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
    except:
        return {}

# --- STEP 3: THE SAVANT ENGINE ---
with st.spinner(f"Synchronizing {league_choice} Markets..."):
    # 1. Scrape the market for current lines
    odds_data = get_automated_odds(config['odds_key'])
    # 2. Scrape the game for the exact clock and score
    live_data = get_precision_scores()
    
    results = []
    for team, line in odds_data.items():
        # Match team names (Fuzzy match: "Lakers" in "LA Lakers")
        match = next((v for k, v in live_data.items() if team in k or k in team), None)
        
        if match and line > 0:
            curr_total = match['h_score'] + match['a_score']
            clock = match['clock']
            
            # --- CLOCK PARSING LOGIC ---
            try:
                if "'" in clock: # Format: "34'"
                    mins = float(clock.replace("'", ""))
                elif ":" in clock: # Format: "Q3 04:30"
                    q = int(clock.split(' ')[0].replace('Q','')) if 'Q' in clock else 1
                    time_part = clock.split(' ')[-1]
                    m, s = map(int, time_part.split(':'))
                    q_len = config['len'] / 4
                    mins = ((q-1) * q_len) + (q_len - m - (s/60))
                else:
                    mins = 0
            except:
                mins = 0

            # --- THE SAVANT MATH ---
            # Don't project until at least 2 minutes have been played to avoid spikes
            if 2 < mins < (config['len'] - 0.5):
                ppm = curr_total / mins
                proj = curr_total + (ppm * (config['len'] - mins) * config['coeff'])
                edge = round(proj - line, 1)

                results.append({
                    "Matchup": team,
                    "Score": f"{match['a_score']}-{match['h_score']}",
                    "Clock": clock,
                    "Savant Proj": round(proj, 1),
                    "Live Line": line,
                    "EDGE": edge
                })

# --- DISPLAY OUTPUT ---
if results:
    df = pd.DataFrame(results).sort_values(by="EDGE", ascending=False)
    
    # Highlight the best edges
    st.dataframe(
        df.style.background_gradient(cmap='RdYlGn', subset=['EDGE']),
        use_container_width=True
    )
    
    # Direct Action Alerts
    for _, row in df.iterrows():
        if abs(row['EDGE']) >= min_edge:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    direction = "OVER" if row['EDGE'] > 0 else "UNDER"
                    st.write(f"### {direction}: {row['Matchup']}")
                    st.write(f"**Proj:** {row['Savant Proj']} | **Bookie:** {row['Live Line']} | **Edge:** {row['EDGE']} pts")
                with col2:
                    st.link_button("💰 BET NOW", FANDUEL_URL, type="primary")
else:
    st.info(f"No active {league_choice} games with data found. If you see a live game on FanDuel, re-scan in a moment.")
