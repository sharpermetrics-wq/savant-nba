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
st.set_page_config(page_title="Savant v6.5: Validated", layout="wide")
st.title("🏀 Savant Global v6.5: Validation Fix")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA", "EuroLeague", "Brazil NBB"])
    
    # --- FIXED MAPPING ---
    # The 'apify_code' MUST match the actor's allowed values exactly.
    league_map = {
        "NBA": {"apify_code": "NBA", "score_tag": "NBA", "len": 48, "coeff": 1.12, "auto": True},
        "EuroLeague": {"apify_code": "UCL", "score_tag": "UCL", "len": 40, "coeff": 0.94, "auto": True},
        "Brazil NBB": {"apify_code": "BRAZIL", "score_tag": "BRAZIL", "len": 40, "coeff": 1.02, "auto": False},
        "College (NCAAB)": {"apify_code": "College-Basketball", "score_tag": "NCAA", "len": 40, "coeff": 1.08, "auto": True}
    }
    config = league_map[league_choice]

    st.divider()
    if st.button("🚀 FULL SYNC SCAN", type="primary"):
        st.rerun()

# --- STEP 1: APYFY ODDS SCRAPER ---
def get_apify_odds(league_code):
    if not config['auto']: return {}
    client = ApifyClient(APIFY_TOKEN)
    
    run_input = {
        "league": league_code, # This will now be "College-Basketball"
        "sportsbook": "FanDuel" 
    }
    
    try:
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input=run_input)
        odds_map = {}
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            home = item.get('homeTeam', '')
            for odd in item.get('odds', []):
                if odd.get('type') == 'overUnder':
                    odds_map[home] = odd.get('overUnder', 0)
        return odds_map
    except Exception as e:
        # We display the actual error if it fails again
        st.error(f"Apify Error: {e}")
        return {}

# --- STEP 2: GLOBAL SCORE PULSE ---
def get_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers).json()
        games = []
        for stage in res.get('Stages', []):
            s_nm = stage.get('Snm', '').upper()
            for event in stage.get('Events', []):
                games.append({
                    "home": event['T1'][0]['Nm'],
                    "h_score": int(event.get('Tr1', 0) or 0),
                    "a_score": int(event.get('Tr2', 0) or 0),
                    "clock": str(event.get('Eps', '00:00')),
                    "league": s_nm
                })
        return games
    except: return []

# --- STEP 3: THE ENGINE ---
with st.spinner(f"Scraping {config['apify_code']}..."):
    odds_data = get_apify_odds(config['apify_code'])
    live_games = get_scores()
    results = []

    for game in live_games:
        # Match against our league tag
        if config['score_tag'] in game['league'] or (league_choice == "College (NCAAB)" and "NCAA" in game['league']):
            total = game['h_score'] + game['a_score']
            clock = game['clock']
            
            try:
                if ":" in clock:
                    parts = clock.split(' ')
                    q_val = parts[0].replace('Q','')
                    q = int(q_val) if q_val.isdigit() else 1
                    m_parts = parts[-1].split(':')
                    m, s = int(m_parts[0]), int(m_parts[1])
                    
                    p_len = config['len'] / 4 if "Q" in clock else config['len'] / 2
                    mins = ((q-1) * p_len) + (p_len - m - (s/60))
                elif "HT" in clock or "HALF" in clock: mins = config['len'] / 2
                else: mins = 5.0
                
                if mins > 2.0:
                    proj = (total / mins) * config['len'] * config['coeff']
                    
                    # Fuzzy team match
                    line = 0
                    for team_key, team_line in odds_data.items():
                        if team_key.upper() in game['home'].upper() or game['home'].upper() in team_key.upper():
                            line = team_line
                            break
                    
                    results.append({
                        "Matchup": game['home'],
                        "Score": f"{game['a_score']}-{game['h_score']}",
                        "Clock": clock,
                        "Savant Proj": round(proj, 1),
                        "Line": line if line > 0 else "---",
                        "EDGE": round(proj - line, 1) if line > 0 else "N/A"
                    })
            except: continue

if results:
    df = pd.DataFrame(results).sort_values(by="Savant Proj", ascending=False)
    st.table(df)
else:
    st.info(f"No live {league_choice} games found.")
