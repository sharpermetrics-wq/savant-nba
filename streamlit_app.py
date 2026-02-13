import streamlit as st
import pandas as pd
import requests
from apify_client import ApifyClient

# --- SECURE CONFIG ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("Missing APIFY_TOKEN in Secrets!")
    st.stop()

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v5.9: Hybrid Engine", layout="wide")
st.title("🏀 Savant Global v5.9: Hybrid Automation")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "Brazil NBB"])
    
    league_map = {
        "NBA": {"val": "NBA", "len": 48, "coeff": 1.12, "auto_odds": True},
        "EuroLeague": {"val": "UCL", "len": 40, "coeff": 0.94, "auto_odds": True},
        "Brazil NBB": {"val": "BRAZIL", "len": 40, "coeff": 1.02, "auto_odds": False}
    }
    config = league_map[league_choice]
    
    if st.button("🚀 REFRESH LIVE DATA", type="primary"):
        st.rerun()

# --- STEP 1: ODDS (NBA/EURO ONLY) ---
def get_odds(league_val):
    client = ApifyClient(APIFY_TOKEN)
    try:
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input={"league": league_val, "sportsbook": "FanDuel"})
        return {item['homeTeam']: item['odds'][0]['overUnder'] for item in client.dataset(run["defaultDatasetId"]).iterate_items() if item.get('odds')}
    except: return {}

# --- STEP 2: GLOBAL SCORE PULSE ---
def get_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers).json()
        games = []
        for stage in res.get('Stages', []):
            league_name = stage.get('Snm', '').upper()
            for event in stage.get('Events', []):
                games.append({
                    "home": event['T1'][0]['Nm'],
                    "h_score": int(event.get('Tr1', 0) or 0),
                    "a_score": int(event.get('Tr2', 0) or 0),
                    "clock": str(event.get('Eps', '00:00')),
                    "league": league_name
                })
        return games
    except: return []

# --- STEP 3: THE ENGINE ---
with st.spinner("Calculating Savant Projections..."):
    odds_data = get_odds(config['val']) if config['auto_odds'] else {}
    live_games = get_scores()
    results = []

    for game in live_games:
        # Match based on League Name (Brazil, NBA, etc.)
        if config['val'] in game['league'] or (league_choice == "Brazil NBB" and "NBB" in game['league']):
            total = game['h_score'] + game['a_score']
            clock = game['clock']
            
            # Clock Parser
            try:
                if ":" in clock:
                    parts = clock.split(' ')
                    q = int(parts[0].replace('Q','')) if 'Q' in parts[0] else 1
                    m, s = map(int, parts[-1].split(':'))
                    mins = ((q-1) * (config['len']/4)) + ((config['len']/4) - m - (s/60))
                elif "HT" in clock or "HALF" in clock: mins = config['len'] / 2
                else: mins = 5.0 # Fallback
            except: mins = 5.0

            if mins > 1:
                proj = (total / mins) * config['len'] * config['coeff']
                line = odds_data.get(game['home'], 0)
                
                results.append({
                    "Matchup": game['home'],
                    "Live Score": f"{game['a_score']}-{game['h_score']}",
                    "Clock": clock,
                    "Savant Proj": round(proj, 1),
                    "FanDuel Line": line if line > 0 else "---",
                    "EDGE": round(proj - line, 1) if line > 0 else "N/A"
                })

# --- DISPLAY ---
if results:
    st.table(pd.DataFrame(results))
    if league_choice == "Brazil NBB":
        st.info("Check FanDuel for the current Live Total. If it's below the Savant Proj, the play is OVER.")
else:
    st.warning(f"No live {league_choice} games detected. Ensure games have tipped off.")
