import streamlit as st
import pandas as pd
import requests
from nba_api.live.nba.endpoints import scoreboard, boxscore

# --- CONFIGURATION ---
API_KEY = "6b10d20e4323876f867026893e161475"
FANDUEL_NBA_URL = "https://sportsbook.fanduel.com/navigation/nba"

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant NBA Live", page_icon="🏀", layout="wide")
st.title("🏀 Savant NBA Live HUD")

# --- SIDEBAR: SETTINGS ---
with st.sidebar:
    st.header("⚙️ Strategy Settings")
    min_edge = st.slider("Min Edge to Bet", 1.0, 10.0, 4.0, help="Point difference between Savant and FanDuel")
    foul_alert = st.number_input("Ref Tightness Alert (FPM)", value=2.2, step=0.1)
    
    st.divider()
    
    if st.button("🚀 SCAN LIVE MARKETS", type="primary"):
        st.rerun()
    
    st.caption(f"Connected to FanDuel API (Key: ...{API_KEY[-4:]})")

# --- FUNCTION 1: FETCH FANDUEL ODDS ---
def fetch_live_odds():
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
            
            # Find FanDuel specifically
            target_book = next((b for b in game['bookmakers'] if b['key'] == 'fanduel'), None)
            
            # Fallback to first available if FD is missing
            if not target_book and game['bookmakers']:
                target_book = game['bookmakers'][0]
                
            if target_book:
                for market in target_book['markets']:
                    if market['key'] == 'totals':
                        line = market['outcomes'][0]['point']
                        odds_map[home_team] = line
                        odds_map[away_team] = line
        return odds_map
    except Exception as e:
        st.error(f"Odds Error: {e}")
        return {}

# --- FUNCTION 2: SAVANT LIVE ENGINE ---
def get_savant_data(odds_map):
    try:
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
    except:
        return pd.DataFrame()

    live_payload = []

    for game in games:
        if game['gameStatus'] != 2: continue # Only Active Games
        
        game_id = game['gameId']
        try:
            stats = boxscore.BoxScore(game_id=game_id).game.get_dict()
        except:
            continue

        home = stats['homeTeam']
        away = stats['awayTeam']
        
        # --- TIME CALCULATIONS ---
        try:
            clock = game['gameClock'].replace('PT','').split('M')[0]
            min_left = int(clock) if clock.isdigit() else 12
            min_played = ((game['period'] - 1) * 12) + (12 - min_left)
        except:
            min_played = 1
            
        if min_played < 5: continue # Wait for sample size

        # --- SAVANT MATH ---
        def get_poss(t):
            return (t['statistics']['fieldGoalsAttempted'] - 
                    t['statistics']['reboundsOffensive'] + 
                    t['statistics']['turnovers'] + 
                    0.44 * t['statistics']['freeThrowsAttempted'])

        total_poss = get_poss(home) + get_poss(away)
        pace_48 = (total_poss / min_played) * 48
        
        fouls = home['statistics']['foulsPersonal'] + away['statistics']['foulsPersonal']
        fpm = fouls / min_played
        
        curr_score = home['score'] + away['score']
        # Ref Adjustment: Efficient Free Throw points
        ref_boost = 4.0 if fpm > foul_alert else 0
        
        savant_proj = (pace_48 * (curr_score / total_poss)) + ref_boost

        # --- LINE MATCHING ---
        book_line = 0
        for team_name, line in odds_map.items():
            if home['teamName'] in team_name or home['teamCity'] in team_name:
                book_line = line
                break
        
        edge = (savant_proj - book_line) if book_line > 0 else 0

        live_payload.append({
            "Matchup": f"{away['teamTricode']} @ {home['teamTricode']}",
            "Qtr": game['period'],
            "Min": round(min_played, 1),
            "Pace": round(pace_48, 1),
            "Fouls/Min": round(fpm, 2),
            "Ref Mode": "🔒 TIGHT" if fpm > foul_alert else "🔓 LOOSE",
            "Savant Proj": round(savant_proj, 1),
            "FanDuel": book_line,
            "EDGE": round(edge, 1)
        })

    return pd.DataFrame(live_payload)

# --- APP LAYOUT ---
with st.spinner("Fetching Live FanDuel Lines & NBA Data..."):
    odds_data = fetch_live_odds()
    df = get_savant_data(odds_data)
    
    if not df.empty:
        # Table Styling
        def color_edge(row):
            if row['EDGE'] >= min_edge:
                return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row)
            elif row['EDGE'] <= -min_edge:
                return ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row)
            return [''] * len(row)

        st.dataframe(
            df.style.apply(color_edge, axis=1).format({"Pace": "{:.1f}", "Savant Proj": "{:.1f}", "FanDuel": "{:.1f}", "EDGE": "{:.1f}"}),
            use_container_width=True
        )
        
        # --- BETTING ALERTS ---
        st.divider()
        for _, row in df.iterrows():
            if abs(row['EDGE']) >= min_edge:
                direction = "OVER" if row['EDGE'] > 0 else "UNDER"
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"### 🚨 {direction}: {row['Matchup']}")
                        st.write(f"Savant: **{row['Savant Proj']}** | FanDuel: **{row['FanDuel']}** (Edge: {row['EDGE']})")
                    with c2:
                        st.link_button(f"💰 BET {direction}", FANDUEL_NBA_URL, use_container_width=True, type="primary")
    else:
        st.info("No active games found. The engine will start automatically when games tip off.")
