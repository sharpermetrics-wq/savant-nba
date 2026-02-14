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
st.set_page_config(page_title="Savant v6.1: Pro Hybrid", page_icon="🏀", layout="wide")
st.title("🏀 Savant Global v6.1: Precision Build")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["Brazil NBB", "NBA", "EuroLeague"])
    
    league_map = {
        "NBA": {"val": "NBA", "len": 48, "coeff": 1.12, "auto": True},
        "EuroLeague": {"val": "UCL", "len": 40, "coeff": 0.94, "auto": True},
        "Brazil NBB": {"val": "BRAZIL", "len": 40, "coeff": 1.02, "auto": False}
    }
    config = league_map[league_choice]

    st.divider()
    st.header("📲 Manual Injection")
    st.info("Use this if the NBB feed lags.")
    m_active = st.checkbox("Enable Manual Override")
    if m_active:
        m_score = st.text_input("Live Score (H-A)", "63-48")
        m_clock = st.text_input("Clock (e.g. Q3 04:30)", "Q3 00:00")

    if st.button("🚀 FULL REFRESH", type="primary"):
        st.rerun()

# --- STEP 1: AUTOMATED ODDS (NBA/EURO) ---
def get_odds(league_val):
    if not config['auto']: return {}
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
        res = requests.get(url, headers=headers, timeout=10).json()
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
with st.spinner("Processing Savant Math..."):
    odds_data = get_odds(config['val'])
    live_games = get_scores()
    results = []

    # Logic: If manual is off, try to find the game. If manual is on, use inputs.
    if m_active:
        try:
            h, a = map(int, m_score.split('-'))
            # Clock parse for manual
            parts = m_clock.split(' ')
            q = int(parts[0].replace('Q',''))
            m, s = map(int, parts[-1].split(':'))
            mins = ((q-1) * 10) + (10 - m - (s/60))
            
            proj = ((h + a) / mins) * config['len'] * config['coeff']
            results.append({"Matchup": "MANUAL ENTRY", "Score": f"{a}-{h}", "Clock": m_clock, "Savant Proj": round(proj, 1), "Line": "---", "EDGE": "N/A"})
        except: st.error("Manual Format: Score '63-48' | Clock 'Q3 04:30'")
    else:
        for game in live_games:
            # BROAD FILTER: Match "BRAZIL", "NBB", or "LNB"
            if any(x in game['league'] for x in ["BRAZIL", "NBB", "LNB"]) or config['val'] in game['league']:
                total = game['h_score'] + game['a_score']
                clock = game['clock']
                
                try:
                    if ":" in clock:
                        parts = clock.split(' ')
                        q = int(parts[0].replace('Q','')) if 'Q' in parts[0] else 1
                        m, s = map(int, parts[-1].split(':'))
                        mins = ((q-1) * 10) + (10 - m - (s/60))
                    elif "HT" in clock or "HALF" in clock: mins = 20.0
                    else: mins = 1.0
                    
                    proj = (total / mins) * config['len'] * config['coeff']
                    line = odds_data.get(game['home'], 0)
                    results.append({
                        "Matchup": game['home'], "Score": f"{game['a_score']}-{game['h_score']}", 
                        "Clock": clock, "Savant Proj": round(proj, 1), 
                        "Line": line if line > 0 else "---", 
                        "EDGE": round(proj - line, 1) if line > 0 else "N/A"
                    })
                except: continue

# --- DISPLAY ---
if results:
    st.table(pd.DataFrame(results))
else:
    st.warning("No live games found. Switch to 'Manual Override' to calculate NBB projections.")
