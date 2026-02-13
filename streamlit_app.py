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
st.set_page_config(page_title="Savant v5.6: Night Owl", page_icon="🏀", layout="wide")
st.title("🏀 Savant Global v5.6: 7:30 PM Tip-Off Build")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "Brazil NBB", "CBA (China)"])
    
    league_map = {
        "NBA": {"val": "NBA", "len": 48, "coeff": 1.12, "teams": []},
        "EuroLeague": {"val": "UCL", "len": 40, "coeff": 0.94, "teams": []},
        "Brazil NBB": {"val": "BRAZIL", "len": 40, "coeff": 1.02, "teams": ["PINHEIROS", "CORINTHIANS", "FLAMENGO", "JOSE", "PAULISTANO", "CAXIAS"]},
        "CBA (China)": {"val": "CHINA", "len": 40, "coeff": 1.05, "teams": ["GUANGDONG", "LIAONING", "BEIJING", "XINJIANG"]}
    }
    config = league_map[league_choice]

    st.divider()
    if st.button("🚀 SYNC LIVE GAMES", type="primary"):
        st.rerun()

# --- STEP 1: SMART ODDS ---
def get_automated_odds(league_name):
    # Only run for NBA/Euro to save Apify credits since NBB/CBA are restricted
    if league_name not in ["NBA", "UCL"]: return {}
    client = ApifyClient(APIFY_TOKEN)
    try:
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input={"league": league_name, "sportsbook": "FanDuel"})
        return {item['homeTeam']: item['odds'][0]['overUnder'] for item in client.dataset(run["defaultDatasetId"]).iterate_items() if item.get('odds')}
    except: return {}

# --- STEP 2: GLOBAL SCORE PULSE ---
def get_precision_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers).json()
        return [{
            "home": event['T1'][0]['Nm'], 
            "h_score": int(event.get('Tr1', 0) or 0), 
            "a_score": int(event.get('Tr2', 0) or 0), 
            "clock": str(event.get('Eps', '00:00')), 
            "league": stage.get('Snm', '').upper()
        } for stage in res.get('Stages', []) for event in stage.get('Events', [])]
    except: return []

# --- STEP 3: THE ENGINE ---
with st.spinner("Scanning Global Feeds..."):
    odds_data = get_automated_odds(config['val'])
    all_live_games = get_precision_scores()
    results = []

    for game in all_live_games:
        # Check if league or team matches our target
        is_match = any(t in game['home'].upper() for t in config['teams']) or config['val'] in game['league']
        
        if is_match:
            total = game['h_score'] + game['a_score']
            # Improved Clock Logic
            try:
                if "'" in game['clock']: mins = float(game['clock'].replace("'", ""))
                elif ":" in game['clock']:
                    parts = game['clock'].split(' ')
                    q = int(parts[0].replace('Q','')) if 'Q' in parts[0] else 1
                    m, s = map(int, parts[-1].split(':'))
                    mins = ((q-1) * 10) + (10 - m - (s/60))
                else: mins = 0
            except: mins = 0

            if mins > 0.5:
                proj = (total / mins) * config['len'] * config['coeff']
                line = odds_data.get(game['home'], 0)
                results.append({
                    "Matchup": game['home'], "Score": f"{game['a_score']}-{game['h_score']}",
                    "Clock": game['clock'], "Savant Proj": round(proj, 1),
                    "FanDuel": line if line > 0 else "---", "EDGE": round(proj - line, 1) if line > 0 else "N/A"
                })

if results:
    st.table(pd.DataFrame(results))
else:
    st.info(f"Waiting for {league_choice} tip-off. Next games start at 7:30 PM Kitchener time.")
    with st.expander("Show all current live basketball globally"):
        st.write([f"{g['home']} ({g['league']})" for g in all_live_games])
