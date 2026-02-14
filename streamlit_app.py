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
st.set_page_config(page_title="Savant v6.7: Rivalry Build", layout="wide")
st.title("🏀 Savant Global v6.7: Ohio vs Miami (OH) Fix")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA", "EuroLeague", "Brazil NBB"])
    
    league_map = {
        "NBA": {"apify": "NBA", "tag": "NBA", "len": 48, "coeff": 1.12},
        "EuroLeague": {"apify": "UCL", "tag": "UCL", "len": 40, "coeff": 0.94},
        "Brazil NBB": {"apify": "BRAZIL", "tag": "BRAZIL", "len": 40, "coeff": 1.02},
        "College (NCAAB)": {"apify": "College-Basketball", "tag": "NCAA", "len": 40, "coeff": 1.08}
    }
    config = league_map[league_choice]

    st.divider()
    # Adding a manual "Team Search" to force find a specific game
    target_team = st.text_input("🎯 Target Team (Optional)", "OHIO").upper()
    
    if st.button("🚀 FORCE SYNC", type="primary"):
        st.rerun()

# --- STEP 1: APYFY ODDS ---
def get_apify_odds(league_code):
    if league_choice == "Brazil NBB": return {}
    client = ApifyClient(APIFY_TOKEN)
    try:
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input={"league": league_code, "sportsbook": "FanDuel"})
        odds = {}
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            home = item.get('homeTeam', '')
            for odd in item.get('odds', []):
                if odd.get('type') == 'overUnder':
                    odds[home] = odd.get('overUnder', 0)
        return odds
    except: return {}

# --- STEP 2: GLOBAL SCORE PULSE ---
def get_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=12).json()
        games = []
        if 'Stages' in res:
            for stage in res['Stages']:
                stage_name = stage.get('Snm', '').upper()
                for event in stage.get('Events', []):
                    games.append({
                        "home": event['T1'][0]['Nm'].upper(),
                        "away": event['T2'][0]['Nm'].upper(),
                        "h_score": int(event.get('Tr1', 0) or 0),
                        "a_score": int(event.get('Tr2', 0) or 0),
                        "clock": str(event.get('Eps', '00:00')),
                        "league": stage_name
                    })
        return games
    except: return []

# --- STEP 3: THE ENGINE ---
with st.spinner(f"Analyzing {league_choice}..."):
    odds_data = get_apify_odds(config['apify'])
    live_games = get_scores()
    results = []

    for game in live_games:
        # MATCHING LOGIC: Search by League Tag OR Manual Team Search
        is_league_match = (config['tag'] in game['league']) or ("USA" in game['league'] and league_choice == "College (NCAAB)")
        is_manual_match = (target_team in game['home'] or target_team in game['away']) if target_team else False
        
        if is_league_match or is_manual_match:
            total = game['h_score'] + game['a_score']
            clock = game['clock']
            
            try:
                # Normalizing NCAA format (20m halves vs 10m quarters)
                if ":" in clock:
                    parts = clock.split(' ')
                    q_val = parts[0].replace('Q','')
                    q = int(q_val) if q_val.isdigit() else 1
                    m, s = map(int, parts[-1].split(':'))
                    # If 'Q' is present, use 10m; otherwise, assume 20m half
                    p_len = 10 if "Q" in clock else 20
                    mins = ((q-1) * p_len) + (p_len - m - (s/60))
                elif "HT" in clock or "HALF" in clock: mins = 20.0
                else: mins = 5.0
                
                if mins > 1.0:
                    proj = (total / mins) * config['len'] * config['coeff']
                    
                    # Fuzzy match for odds
                    line = 0
                    for k, v in odds_data.items():
                        if k.upper() in game['home'] or game['home'] in k.upper():
                            line = v
                            break
                    
                    results.append({
                        "Matchup": f"{game['away']} @ {game['home']}",
                        "Score": f"{game['a_score']}-{game['h_score']}",
                        "Clock": clock,
                        "Savant Proj": round(proj, 1),
                        "Line": line if line > 0 else "---",
                        "EDGE": round(proj - line, 1) if line > 0 else "N/A"
                    })
            except: continue

if results:
    st.table(pd.DataFrame(results).sort_values(by="Savant Proj", ascending=False))
else:
    st.info(f"Searching for {target_team}... Tip: If the game just tipped off, wait 2 mins for data to populate.")
