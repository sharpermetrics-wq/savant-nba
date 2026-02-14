import streamlit as st
import pandas as pd
import requests

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v13: ESPN Native", layout="wide")
st.title("🏀 Savant v13: ESPN BET Integration")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA", "WNBA"])
    
    # ESPN Configuration
    league_map = {
        "NBA": {
            "url": "basketball/nba", 
            "len": 48, 
            "coeff": 1.12
        },
        "College (NCAAB)": {
            "url": "basketball/mens-college-basketball", 
            "len": 40, 
            "coeff": 1.08
        },
        "WNBA": {
            "url": "basketball/wnba", 
            "len": 40, 
            "coeff": 1.05
        }
    }
    config = league_map[league_choice]

    st.divider()
    if st.button("🚀 REFRESH DATA", type="primary"):
        st.rerun()

# --- STEP 1: FETCH ESPN DATA & ODDS TOGETHER ---
def get_espn_data(sport_path):
    # This single endpoint gives us Scores, Clock, AND ESPN Bet Odds
    base_url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard"
    try:
        res = requests.get(base_url, timeout=10).json()
        games = []
        
        for event in res.get('events', []):
            comp = event['competitions'][0]
            status = event['status']
            
            # 1. Get Teams & Scores
            home_team = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            away_team = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            
            # 2. Get Clock & Period
            clock_display = status.get('displayClock', '0:00')
            period = status.get('period', 1)
            state = status.get('type', {}).get('state', 'pre') 
            
            # 3. GET ESPN BET ODDS (Native Extraction)
            # The API usually provides a list of odds. We take the first one (Provider: ESPN BET)
            line = 0.0
            spread = "N/A"
            if 'odds' in comp:
                try:
                    # Look for the 'overUnder' field in the first odds provider
                    odds_obj = comp['odds'][0]
                    line = float(odds_obj.get('overUnder', 0))
                    spread = odds_obj.get('details', 'N/A') # e.g. "MIA -4.5"
                except:
                    line = 0.0

            games.append({
                "matchup": event['name'],
                "home": home_team['team']['displayName'],
                "away": away_team['team']['displayName'],
                "h_score": int(home_team.get('score', 0)),
                "a_score": int(away_team.get('score', 0)),
                "clock": clock_display,
                "period": period,
                "status": state,
                "espn_line": line,
                "spread": spread
            })
        return games
    except Exception as e:
        st.error(f"ESPN Feed Error: {e}")
        return []

# --- STEP 2: THE ENGINE ---
with st.spinner(f"Pulling Live Data & ESPN BET Lines..."):
    live_games = get_espn_data(config['url'])
    
    # Filter for active games only
    active_games = [g for g in live_games if g['status'] == 'in']
    
    results = []

    for game in active_games:
        total = game['h_score'] + game['a_score']
        clock = game['clock']
        period = game['period']
        line = game['espn_line']
        
        # --- CLOCK PARSER ---
        try:
            mins_played = 0.0
            
            # Clock String to Ints
            if ":" in clock:
                m, s = map(int, clock.split(':'))
            else:
                m, s = 0, 0
            
            # NCAA Logic (2 Halves)
            if league_choice == "College (NCAAB)":
                if period == 1:
                    mins_played = 20.0 - m - (s/60.0)
                elif period == 2:
                    mins_played = 20.0 + (20.0 - m - (s/60.0))
                elif period >= 3: # Overtime
                    mins_played = 40.0 + ((period-2) * 5.0) - m - (s/60.0)
            
            # NBA Logic (4 Quarters)
            else:
                q_len = 12.0
                if period <= 4:
                    mins_played = ((period - 1) * q_len) + (q_len - m - (s/60.0))
                else: 
                    mins_played = 48.0 + ((period-4) * 5.0) - m - (s/60.0)
            
            # Halftime Handling
            if game['status'] == 'halftime':
                mins_played = config['len'] / 2

            # SAVANT MATH
            if mins_played > 2.0:
                proj = (total / mins_played) * config['len'] * config['coeff']
                
                # Calculate Edge (Only if line exists)
                edge = round(proj - line, 1) if line > 0 else "N/A"
                
                results.append({
                    "Matchup": game['matchup'],
                    "Score": f"{game['a_score']}-{game['h_score']}",
                    "Clock": f"P{period} {clock}",
                    "ESPN Line": line if line > 0 else "---",
                    "Savant Proj": round(proj, 1),
                    "EDGE": edge
                })
        except: continue

# --- DISPLAY ---
if results:
    st.success(f"Tracking {len(results)} Live Games via ESPN BET")
    # Sort by highest EDGE for betting value
    df = pd.DataFrame(results)
    
    # If we have edges, try to sort by absolute value of EDGE (magnitude of opportunity)
    if "EDGE" in df.columns and len(df) > 0:
        # Create temporary sort column
        df['sort_val'] = pd.to_numeric(df['EDGE'], errors='coerce').abs()
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])

    st.table(df)
else:
    st.info(f"No active {league_choice} games found.")
    if live_games:
        st.write("Upcoming / Finished Games:")
        st.write([f"{g['matchup']} ({g['status']})" for g in live_games[:5]])
