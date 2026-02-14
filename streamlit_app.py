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
st.set_page_config(page_title="Savant v6.3: Apify CBB", layout="wide")
st.title("🏀 Savant Global v6.3: Apify College Automation")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA", "EuroLeague", "Brazil NBB"])
    
    # Mapping for Apify Actor
    # CBB = College Basketball, CFB = College Football
    league_map = {
        "NBA": {"val": "NBA", "len": 48, "coeff": 1.12, "auto": True},
        "EuroLeague": {"val": "UCL", "len": 40, "coeff": 0.94, "auto": True},
        "Brazil NBB": {"val": "BRAZIL", "len": 40, "coeff": 1.02, "auto": False},
        "College (NCAAB)": {"val": "CBB", "len": 40, "coeff": 1.08, "auto": True}
    }
    config = league_map[league_choice]

    st.divider()
    if st.button("🚀 FULL SYNC SCAN", type="primary"):
        st.rerun()

# --- STEP 1: APYFY ODDS SCRAPER ---
def get_apify_odds(league_val):
    if not config['auto']: return {}
    client = ApifyClient(APIFY_TOKEN)
    
    # We use the 'harvest' actor because it supports 'CBB'
    run_input = {
        "league": league_val, 
        "sportsbook": "FanDuel" 
    }
    
    try:
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input=run_input)
        odds_map = {}
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            home = item.get('homeTeam', '')
            # Look for the 'Totals' market in the nested odds list
            for odd in item.get('odds', []):
                if odd.get('type') == 'overUnder':
                    odds_map[home] = odd.get('overUnder', 0)
        return odds_map
    except Exception as e:
        st.warning(f"Apify Note: {e}")
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
with st.spinner(f"Apify is scraping {league_choice} lines..."):
    odds_data = get_apify_odds(config['val'])
    live_games = get_scores()
    results = []

    for game in live_games:
        # Match 'CBB' to 'NCAA' in the score feed
        is_college = (league_choice == "College (NCAAB)" and "NCAA" in game['league'])
        is_pro = (config['val'] in game['league'])
        
        if is_college or is_pro:
            total = game['h_score'] + game['a_score']
            clock = game['clock']
            
            try:
                # Normalizing clock for 40m games (NCAA/Euro/NBB)
                if ":" in clock:
                    parts = clock.split(' ')
                    q_val = parts[0].replace('Q','')
                    q = int(q_val) if q_val.isdigit() else 1
                    m, s = map(int, parts[-1].split(':'))
                    # NCAA is often 20m halves; if 'Q' isn't there, treat as half
                    p_len = config['len'] / 4 if "Q" in clock else config['len'] / 2
                    mins = ((q-1) * p_len) + (p_len - m - (s/60))
                elif "HT" in clock or "HALF" in clock: mins = config['len'] / 2
                else: mins = 2.0
                
                if mins > 2.0:
                    proj = (total / mins) * config['len'] * config['coeff']
                    # Fuzzy match team names (e.g. 'Duke Blue Devils' -> 'Duke')
                    line = 0
                    for team_name, team_line in odds_data.items():
                        if team_name in game['home'] or game['home'] in team_name:
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
    st.info("No live games found. NCAA games usually peak on Saturdays!")
