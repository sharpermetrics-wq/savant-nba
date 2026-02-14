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
st.set_page_config(page_title="Savant v12: Ironclad", layout="wide")
st.title("🏀 Savant v12: ESPN Integrated Engine")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA", "WNBA"])
    
    # ESPN API Endpoint Mappings
    league_map = {
        "NBA": {
            "url": "basketball/nba", 
            "apify": "NBA", 
            "len": 48, 
            "coeff": 1.12
        },
        "College (NCAAB)": {
            "url": "basketball/mens-college-basketball", 
            "apify": "College-Basketball", 
            "len": 40, 
            "coeff": 1.08
        },
        "WNBA": {
            "url": "basketball/wnba", 
            "apify": "WNBA", 
            "len": 40, 
            "coeff": 1.05
        }
    }
    config = league_map[league_choice]

    st.divider()
    if st.button("🚀 SYNC LIVE FEED", type="primary"):
        st.rerun()

# --- STEP 1: ESPN DATA FETCH (THE FIX) ---
def get_espn_data(sport_path):
    # This is the open public API used by the ESPN App. It is extremely reliable.
    base_url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard"
    try:
        res = requests.get(base_url, timeout=10).json()
        games = []
        
        for event in res.get('events', []):
            comp = event['competitions'][0]
            status = event['status']
            
            # Extract Teams & Scores
            home_team = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            away_team = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            
            # Extract Clock
            # ESPN sends clock as seconds remaining in period, or displayValue like "10:00"
            clock_display = status.get('displayClock', '0:00')
            period = status.get('period', 1)
            state = status.get('type', {}).get('state', 'pre') # 'in', 'post', 'pre'
            
            games.append({
                "matchup": event['name'],
                "home": home_team['team']['displayName'],
                "away": away_team['team']['displayName'],
                "h_score": int(home_team.get('score', 0)),
                "a_score": int(away_team.get('score', 0)),
                "clock": clock_display,
                "period": period,
                "status": state
            })
        return games
    except Exception as e:
        st.error(f"ESPN Feed Error: {e}")
        return []

# --- STEP 2: ODDS FETCH (APIFY) ---
def get_odds(league_code):
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

# --- STEP 3: THE ENGINE ---
with st.spinner(f"Connecting to ESPN {league_choice} Feed..."):
    live_games = get_espn_data(config['url'])
    
    # Only fetch odds if games are actually live to save credits
    active_games = [g for g in live_games if g['status'] == 'in']
    odds_data = get_odds(config['apify']) if active_games else {}
    
    results = []

    for game in active_games:
        total = game['h_score'] + game['a_score']
        clock = game['clock']
        period = game['period']
        
        # --- ROBUST CLOCK PARSER (ESPN FORMAT) ---
        try:
            mins_played = 0.0
            
            # 1. Parse "MM:SS" from ESPN
            if ":" in clock:
                m, s = map(int, clock.split(':'))
            else:
                m, s = 0, 0 # Handle weird states
            
            # 2. Logic for NCAA (2 Halves)
            if league_choice == "College (NCAAB)":
                if period == 1:
                    mins_played = 20.0 - m - (s/60.0)
                elif period == 2:
                    mins_played = 20.0 + (20.0 - m - (s/60.0))
                elif period >= 3: # Overtime
                    mins_played = 40.0 + ((period-2) * 5.0) - m - (s/60.0)
            
            # 3. Logic for NBA (4 Quarters)
            else:
                q_len = 12.0
                if period <= 4:
                    mins_played = ((period - 1) * q_len) + (q_len - m - (s/60.0))
                else: # Overtime
                    mins_played = 48.0 + ((period-4) * 5.0) - m - (s/60.0)
            
            # 4. Halftime Check
            if game['status'] == 'halftime':
                mins_played = config['len'] / 2

            # CALCULATION
            if mins_played > 2.0:
                proj = (total / mins_played) * config['len'] * config['coeff']
                
                # Fuzzy Match Odds
                line = 0
                for k, v in odds_data.items():
                    # Check if "Ohio" is in "Ohio Bobcats"
                    if k.upper() in game['home'].upper() or game['home'].upper() in k.upper():
                        line = v
                        break
                
                results.append({
                    "Matchup": game['matchup'],
                    "Score": f"{game['a_score']}-{game['h_score']}",
                    "Clock": f"P{period} {clock}",
                    "Savant Proj": round(proj, 1),
                    "FanDuel Line": line if line > 0 else "---",
                    "EDGE": round(proj - line, 1) if line > 0 else "N/A"
                })
        except: continue

# --- DISPLAY ---
if results:
    st.success(f"Tracking {len(results)} Live Games")
    st.table(pd.DataFrame(results).sort_values(by="Savant Proj", ascending=False))
else:
    st.info(f"No active {league_choice} games found. (ESPN Feed is Connected).")
    # Debug: Show upcoming games so you know it's working
    if live_games:
        st.write("Upcoming / Finished Games on Feed:")
        st.write([f"{g['matchup']} ({g['status']})" for g in live_games[:5]])
