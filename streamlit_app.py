import streamlit as st
import pandas as pd
import requests
from apify_client import ApifyClient

# --- SECURE CONFIG ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("Missing APIFY_TOKEN in Streamlit Secrets! (Go to Dashboard -> Settings -> Secrets)")
    st.stop()

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v5.6: Live NBB", page_icon="🏀", layout="wide")
st.title("🏀 Savant Global v5.6: NBB Live Sync")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "Brazil NBB", "CBA (China)"])
    
    # League Specific Mappings
    league_map = {
        "NBA": {"val": "NBA", "len": 48, "coeff": 1.12, "teams": []},
        "EuroLeague": {"val": "UCL", "len": 40, "coeff": 0.94, "teams": []},
        "Brazil NBB": {"val": "BRAZIL", "len": 40, "coeff": 1.02, "teams": ["PINHEIROS", "CORINTHIANS", "PAULISTANO", "CAXIAS", "FLAMENGO", "JOSE"]},
        "CBA (China)": {"val": "CHINA", "len": 40, "coeff": 1.05, "teams": ["GUANGDONG", "LIAONING"]}
    }
    config = league_map[league_choice]

    st.divider()
    st.header("🛠️ Controls")
    use_manual = st.checkbox("Force Manual Entry (API Failsafe)")
    if use_manual:
        m_score = st.text_input("Manual Score (e.g. 42-35)", "0-0")
        m_clock = st.slider("Manual Mins Played", 0.0, float(config['len']), 20.0)

    if st.button("🚀 FULL SYNC REFRESH", type="primary"):
        st.rerun()

# --- STEP 1: ODDS FETCH (APIFY) ---
def get_automated_odds(league_val):
    # Skip NBB/CBA for Apify as they are restricted; return empty to trigger 'Manual' label
    if league_val not in ["NBA", "UCL"]: return {}
    client = ApifyClient(APIFY_TOKEN)
    try:
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input={"league": league_val, "sportsbook": "FanDuel"})
        return {item['homeTeam']: item['odds'][0]['overUnder'] for item in client.dataset(run["defaultDatasetId"]).iterate_items() if item.get('odds')}
    except: return {}

# --- STEP 2: SCORE PULSE (LIVESCORE) ---
def get_precision_scores():
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        games = []
        for stage in res.get('Stages', []):
            l_name = stage.get('Snm', '').replace(" ", "").upper()
            for event in stage.get('Events', []):
                games.append({
                    "home": event['T1'][0]['Nm'],
                    "h_score": int(event.get('Tr1', 0) or 0),
                    "a_score": int(event.get('Tr2', 0) or 0),
                    "clock": str(event.get('Eps', '00:00')),
                    "league": l_name
                })
        return games
    except: return []

# --- STEP 3: THE ENGINE ---
with st.spinner(f"Syncing {league_choice}..."):
    odds_data = get_automated_odds(config['val'])
    live_games = get_precision_scores()
    results = []

    for game in live_games:
        # PITCH-BLACK FILTERING: Match by team list or league keyword
        is_match = any(t in game['home'].upper() for t in config['teams']) or config['val'] in game['league']
        
        if is_match or use_manual:
            h, a = (int(m_score.split('-')[1]), int(m_score.split('-')[0])) if use_manual else (game['h_score'], game['a_score'])
            total = h + a
            
            # Clock Parsing
            if use_manual:
                mins = m_clock
                clock_label = f"{mins}m"
            else:
                clock_label = game['clock']
                try:
                    if "'" in clock_label: mins = float(clock_label.replace("'", ""))
                    elif ":" in clock_label:
                        parts = clock_label.split(' ')
                        q = int(parts[0].replace('Q','')) if 'Q' in parts[0] else 1
                        m, s = map(int, parts[-1].split(':'))
                        mins = ((q-1) * 10) + (10 - m - (s/60))
                    elif "HT" in clock_label or "HALF" in clock_label: mins = 20.0
                    else: mins = 15.0
                except: mins = 15.0

            if mins > 0.5:
                # Savant Projection
                proj = (total / mins) * config['len'] * config['coeff']
                line = odds_data.get(game['home'], 0)
                
                results.append({
                    "Matchup": game['home'],
                    "Score": f"{a}-{h}",
                    "Clock": clock_label,
                    "Savant Proj": round(proj, 1),
                    "FanDuel": line if line > 0 else "---",
                    "EDGE": round(proj - line, 1) if line > 0 else "N/A"
                })
            
            if use_manual: break # Only process one manual game

# --- DISPLAY ---
if results:
    st.table(pd.DataFrame(results))
    if league_choice == "Brazil NBB":
        st.info("💡 **Live Tracking:** If 'FanDuel' says '---', look at your phone. If the live total is LOWER than the Savant Proj, bet the OVER.")
else:
    st.warning(f"No live {league_choice} games found. Tip: Check the 'Global Feed' expander below.")
    with st.expander("Global Basketball Feed (Raw)"):
        st.write([f"{g['home']} | {g['league']}" for g in live_games])
