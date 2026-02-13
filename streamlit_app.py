import streamlit as st
import pandas as pd
import requests
import time
from nba_api.live.nba.endpoints import scoreboard, boxscore

# --- CONFIGURATION ---
# ⚠️ SECURITY WARNING: You are hardcoding this key in a public file. 
# If someone finds your GitHub, they can use your quota.
API_KEY = "6b10d20e4323876f867026893e161475"
PREFERRED_BOOK = "fanduel"  # Prioritize FanDuel

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant NBA (FanDuel)", page_icon="🏀", layout="wide")
st.title("🏀 Savant NBA: Auto-Pilot (FanDuel Mode)")

# --- SIDEBAR: SETTINGS ---
with st.sidebar:
    st.header("⚙️ Savant Strategy")
    min_edge = st.slider("Min Edge to Bet", 1.0, 10.0, 4.0, help="Only show bets where Savant > FanDuel by this amount")
    
    st.divider()
    
    if st.button("🚀 SCAN FANDUEL LIVE", type="primary"):
        st.rerun()
    
    st.caption(f"Using API Key: ...{API_KEY[-4:]}")

# --- FUNCTION 1: FETCH ODDS (FANDUEL PRIORITY) ---
def fetch_live_odds():
    # URL for NBA Odds (US/Canada Region)
    url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds/?apiKey={API_KEY}&regions=us&markets=totals&oddsFormat=american"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if 'message' in data:
            st.error(f"Odds API Error: {data['message']}")
            return {}

        odds_map = {}
        for game in data:
            home_team = game['home_team']
            away_team = game['away_team']
            
            # 1. Look for PREFERRED_BOOK (FanDuel)
            target_book = None
            for book in game['bookmakers']:
                if book['key'] == PREFERRED_BOOK:
                    target_book = book
                    break
            
            # 2. Fallback if FanDuel is missing
            if not target_book and game['bookmakers']:
                target_book = game['bookmakers'][0] # Take whatever is available
                
            if target_book:
                # Extract Over/Under Line
                for market in target_book['markets']:
                    if market['key'] == 'totals':
                        line = market['outcomes'][0]['point']
                        # Map to both team names for lookup
                        odds_map[home_team] = line
                        odds_map[away_team] = line
                        
        return odds_map

    except Exception as e:
        st.error(f"Failed to fetch odds: {e}")
        return {}

# --- FUNCTION 2: FETCH SAVANT LIVE DATA ---
def get_savant_data(odds_map):
    try:
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
    except:
        st.warning("Could not connect to NBA API. Are games live?")
        return pd.DataFrame()

    live_payload = []

    for game in games:
        if game['gameStatus'] != 2: continue # Only Live Games
        
        game_id = game['gameId']
        try:
            stats = boxscore.BoxScore(game_id=game_id).game.get_dict()
        except:
            continue

        home = stats['homeTeam']
        away = stats['awayTeam']
        
        # Time Logic
        try:
            clock = game['gameClock'].replace('PT','').split('M')[0]
            min_left = int(clock) if clock.isdigit() else 12
            min_played = ((game['period'] - 1) * 12) + (12 - min_left)
        except:
            min_played = 1
            
        if min_played < 5: continue

        # --- METRICS ---
        def get_poss(t):
            return (t['statistics']['fieldGoalsAttempted'] - 
                    t['statistics']['reboundsOffensive'] + 
                    t['statistics']['turnovers'] + 
                    0.44 * t['statistics']['freeThrowsAttempted'])

        poss = get_poss(home) + get_poss(away)
        pace = (poss / min_played) * 48
        
        fouls = home['statistics']['foulsPersonal'] + away['statistics']['foulsPersonal']
        fpm = fouls / min_played
        
        curr_score = home['score'] + away['score']
        
        # Referee Adjustment (Tight whistle = Free throws = Efficiency)
        ref_boost = 4.0 if fpm > 2.1 else 0
        
        savant_proj = (pace * (curr_score / poss)) + ref_boost

        # --- MATCHING WITH FANDUEL ---
        book_line = 0
        # Fuzzy match team names (e.g. "Lakers" in "Los Angeles Lakers")
        for team_full, line in odds_map.items():
            if home['teamName'] in team_full or home['teamCity'] in team_full:
                book_line = line
                break
        
        edge = (savant_proj - book_line) if book_line > 0 else 0

        live_payload.append({
            "Matchup": f"{away['teamTricode']} @ {home['teamTricode']}",
            "Qtr": game['period'],
            "Min": round(min_played, 1),
            "Pace": round(pace, 1),
            "Fouls/Min": round(fpm, 2),
            "Ref Mode": "🔒 TIGHT" if fpm > 2.1 else "🔓 LOOSE",
            "Savant Proj": round(savant_proj, 1),
            "FanDuel Line": book_line,
            "EDGE": round(edge, 1)
        })

    return pd.DataFrame(live_payload)

# --- MAIN APP EXECUTION ---
with st.spinner("Fetching FanDuel Lines & Scanning Live Data..."):
    # 1. Fetch FanDuel Odds
    odds_data = fetch_live_odds()
    
    # 2. Fetch Live Stats
    df = get_savant_data(odds_data)
    
    if not df.empty:
        st.success(f"Synced {len(df)} Live Games")
        
        # Styling
        def highlight(row):
            if row['EDGE'] >= min_edge:
                return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row) # Green
            elif row['EDGE'] <= -min_edge:
                return ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row) # Red
            return [''] * len(row)

        st.dataframe(
            df.style.apply(highlight, axis=1).format({
                "Pace": "{:.1f}", 
                "Savant Proj": "{:.1f}", 
                "FanDuel Line": "{:.1f}", 
                "EDGE": "{:.1f}"
            }), 
            use_container_width=True
        )
        
        # Alerts
        for _, row in df.iterrows():
            if abs(row['EDGE']) >= min_edge:
                direction = "OVER" if row['EDGE'] > 0 else "UNDER"
                st.markdown(f"### 🚨 BET {direction}: {row['Matchup']}")
                st.write(f"Proj: **{row['Savant Proj']}** vs FanDuel: **{row['FanDuel Line']}**")
                
                if "TIGHT" in row['Ref Mode'] and direction == "OVER":
                     st.write("➕ **Bonus:** Refs are calling it tight (Free Throws expected)")
                st.divider()
    else:
        st.info("No active games found. (Waiting for tip-off...)")
        
