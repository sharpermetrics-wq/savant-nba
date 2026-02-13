import streamlit as st
import pandas as pd
import json
from nba_api.live.nba.endpoints import scoreboard, boxscore

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Savant NBA Live",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🏀 Savant NBA Live Dashboard")
st.markdown("### *Live Pace & Referee Arb Engine*")

# --- SIDEBAR: SETTINGS & UPLOAD ---
with st.sidebar:
    st.header("1. Upload Odds")
    uploaded_file = st.file_uploader("Drop your 'Odds.json' here", type=['json'])
    
    st.divider()
    
    st.header("2. Savant Settings")
    min_edge = st.slider("Minimum Edge to Bet", 1.0, 15.0, 5.0, help="Only show games where Savant Projection > Book Line by this amount.")
    foul_threshold = st.number_input("Referee Foul Threshold (FPM)", value=2.0, step=0.1, help="If Fouls Per Minute > this number, the Ref Mode is 'TIGHT'.")
    
    st.divider()
    
    if st.button("🔄 Refresh Live Data", type="primary"):
        st.rerun()

# --- HELPER: PARSE ODDS JSON ---
def load_odds(upload):
    """
    Parses the uploaded JSON.
    Expected Format: [{"Team": "LAL", "Total": 225.5}, ...]
    """
    if upload is not None:
        try:
            data = json.load(upload)
            # Create a dictionary for quick lookup: {"LAL": 225.5, "BOS": 218.0}
            odds_dict = {}
            for row in data:
                # Flexible parsing: try uppercase and standard keys
                team = row.get('Team', row.get('team', 'UNK'))
                total = row.get('Total', row.get('total', 0))
                odds_dict[team] = float(total)
            return odds_dict
        except Exception as e:
            st.error(f"Error reading JSON: {e}")
            return {}
    return {}

# --- CORE ENGINE: FETCH LIVE DATA ---
def get_live_savant_data(odds_map):
    try:
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
    except Exception as e:
        st.error(f"NBA API Error: {e}")
        return pd.DataFrame()

    live_payload = []

    for game in games:
        # Filter: Only include active games (Status 2)
        if game['gameStatus'] != 2: 
            continue
            
        game_id = game['gameId']
        
        try:
            # Pull Live Boxscore
            box = boxscore.BoxScore(game_id=game_id)
            stats = box.game.get_dict()
        except:
            continue

        # Extract Teams
        home = stats['homeTeam']
        away = stats['awayTeam']
        h_code = home['teamTricode']
        a_code = away['teamTricode']

        # --- TIME CALCULATIONS ---
        try:
            # Game clock format is "PT08M22.00S"
            clock_str = game['gameClock']
            minutes_left = int(clock_str.replace('PT','').split('M')[0])
            minutes_played = ((game['period'] - 1) * 12) + (12 - minutes_left)
        except:
            minutes_played = 1 # Fallback safety
            
        if minutes_played < 5: 
            continue # Skip games with <5 mins of sample size

        # --- SAVANT METRIC 1: LIVE PACE ---
        # Formula: FGA - ORB + TOV + (0.44 * FTA)
        def calc_poss(t):
            return (t['statistics']['fieldGoalsAttempted'] - 
                    t['statistics']['reboundsOffensive'] + 
                    t['statistics']['turnovers'] + 
                    (0.44 * t['statistics']['freeThrowsAttempted']))

        total_poss = calc_poss(home) + calc_poss(away)
        live_pace = (total_poss / minutes_played) * 48
        
        # --- SAVANT METRIC 2: REFEREE FACTOR ---
        # High fouls = Stopped Clock = Higher Efficiency
        total_fouls = home['statistics']['foulsPersonal'] + away['statistics']['foulsPersonal']
        fpm = total_fouls / minutes_played # Fouls Per Minute
        
        # --- SAVANT PROJECTION ---
        current_score = home['score'] + away['score']
        pts_per_poss = current_score / total_poss if total_poss > 0 else 0
        
        # Referee Adjustment Logic
        # If Fouls > Threshold, we add a "Ref Boost" (Free Throws are efficient points)
        ref_adj = 4.5 if fpm > foul_threshold else 0
        
        final_proj = (live_pace * pts_per_poss) + ref_adj

        # --- ODDS MATCHING ---
        # Look for either team in the odds dictionary
        book_line = odds_map.get(h_code, odds_map.get(a_code, 0))
        
        edge = 0
        if book_line > 0:
            edge = final_proj - book_line

        live_payload.append({
            "Matchup": f"{a_code} @ {h_code}",
            "Qtr": game['period'],
            "Min": round(minutes_played, 1),
            "Score": current_score,
            "Pace": round(live_pace, 1),
            "Fouls/Min": round(fpm, 2),
            "Ref Mode": "🔒 TIGHT" if fpm > foul_threshold else "🔓 LOOSE",
            "Savant Proj": round(final_proj, 1),
            "Book Line": book_line,
            "EDGE": round(edge, 1)
        })

    return pd.DataFrame(live_payload)

# --- MAIN APP EXECUTION ---

# 1. Load User Odds
odds_data = load_odds(uploaded_file)

if not uploaded_file:
    st.info("👋 Welcome to Savant NBA Live! Please upload your `Odds.json` in the sidebar to start scanning.")

# 2. Run Engine if Odds are present OR just to see live stats
if st.button("Run Scan Now") or uploaded_file:
    with st.spinner("Fetching live NBA data..."):
        df = get_live_savant_data(odds_data)
    
    if not df.empty:
        # --- DISPLAY STYLING ---
        def highlight_edge(row):
            styles = [''] * len(row)
            if row['EDGE'] >= min_edge:
                styles = ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row) # Green
            elif row['EDGE'] <= -min_edge:
                styles = ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row) # Red
            return styles

        st.success(f"Scanned {len(df)} Live Games")
        
        # Display the main table
        st.dataframe(
            df.style.apply(highlight_edge, axis=1).format({
                "Pace": "{:.1f}", 
                "Fouls/Min": "{:.2f}", 
                "Savant Proj": "{:.1f}", 
                "Book Line": "{:.1f}", 
                "EDGE": "{:.1f}"
            }),
            use_container_width=True,
            height=500
        )
        
        # --- ALERTS SECTION ---
        st.subheader("🔥 Actionable Alerts")
        found_alert = False
        
        col1, col2 = st.columns(2)
        
        for index, row in df.iterrows():
            # OVER ALERT
            if row['EDGE'] >= min_edge:
                found_alert = True
                with col1:
                    st.success(f"**BET OVER: {row['Matchup']}**")
                    st.write(f"Projection: **{row['Savant Proj']}** vs Book: **{row['Book Line']}**")
                    st.write(f"Reason: Edge is +{row['EDGE']}")
                    if "TIGHT" in row['Ref Mode']:
                        st.write("➕ **Ref Factor:** High Fouls (Tight Whistle)")
                    st.divider()
            
            # UNDER ALERT
            elif row['EDGE'] <= -min_edge:
                found_alert = True
                with col2:
                    st.error(f"**BET UNDER: {row['Matchup']}**")
                    st.write(f"Projection: **{row['Savant Proj']}** vs Book: **{row['Book Line']}**")
                    st.write(f"Reason: Edge is {row['EDGE']}")
                    if "LOOSE" in row['Ref Mode']:
                        st.write("➕ **Ref Factor:** Low Fouls (Game Moving Fast)")
                    st.divider()

        if not found_alert:
            st.info(f"No edges found > {min_edge} points. The market is sharp right now.")
            
    else:
        st.warning("No active games found. (Are games in progress?)")
      
