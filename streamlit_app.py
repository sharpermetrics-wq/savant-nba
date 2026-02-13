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
st.set_page_config(page_title="Savant v5.5: NBB Precision", page_icon="🏀", layout="wide")
st.title("🏀 Savant Global v5.5: The NBB Fix")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "Brazil NBB", "CBA (China)"])
    
    league_map = {
        "NBA": {"mode": "direct", "val": "NBA", "len": 48, "coeff": 1.12},
        "EuroLeague": {"mode": "direct", "val": "UCL", "len": 40, "coeff": 0.94},
        "Brazil NBB": {"mode": "manual", "val": "NBBBRAZIL", "len": 40, "coeff": 1.02},
        "CBA (China)": {"mode": "manual", "val": "CHINACBA", "len": 40, "coeff": 1.05}
    }
    config = league_map[league_choice]

    st.divider()
    if st.button("🚀 FULL SYNC SCAN", type="primary"):
        st.rerun()

# --- STEP 1: SMART ODDS SCRAPER ---
def get_automated_odds(config_item):
    if config_item['mode'] == "manual":
        return {} # Scrapers restricted for NBB/CBA
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
    except: return {}

# --- STEP 2: REAL-TIME SCORE PULSE ---
def get_precision_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        score_data = []
        if isinstance(res, dict) and 'Stages' in res:
            for stage in res['Stages']:
                league_nm = stage.get('Snm', '').replace(" ", "").upper()
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
with st.spinner(f"Scanning {league_choice}..."):
    odds_data = get_automated_odds(config)
    live_data = get_precision_scores()
    results = []
    
    for game in live_data:
        # EXACT LEAGUE MATCHING for NBB
        if config['val'] in game['league']:
            curr_total = game['h_score'] + game['a_score']
            clock = game['clock']
            
            # --- IMPROVED CLOCK PARSER ---
            try:
                if "'" in clock: 
                    mins = float(clock.replace("'", ""))
                elif ":" in clock:
                    # Logic for "Q2 04:30"
                    parts = clock.split(' ')
                    q = int(parts[0].replace('Q','')) if 'Q' in parts[0] else 1
                    m, s = map(int, parts[-1].split(':'))
                    q_len = config['len'] / 4
                    mins = ((q-1) * q_len) + (q_len - m - (s/60))
                else: 
                    mins = 10 # Default fallback
            except: mins = 10

            if mins > 0.5:
                ppm = curr_total / mins
                proj = curr_total + (ppm * (config['len'] - mins) * config['coeff'])
                line = odds_data.get(game['home'], 0)
                edge = round(proj - line, 1) if line > 0 else "N/A"

                results.append({
                    "Matchup": game['home'],
                    "Score": f"{game['h_score']}-{game['a_score']}",
                    "Clock": clock,
                    "Savant Proj": round(proj, 1),
                    "FanDuel": line if line > 0 else "---",
                    "EDGE": edge
                })

# --- DISPLAY ---
if results:
    st.table(pd.DataFrame(results))
else:
    st.warning(f"No live {league_choice} games found. Tip: They may be in halftime.")
    with st.expander("Debug: All Live Leagues"):
        st.write(list(set([g['league'] for g in live_data])))
