import streamlit as st
import pandas as pd
import requests

# --- CONFIGURATION ---
API_KEY = "6b10d20e4323876f867026893e161475"
FANDUEL_URL = "https://sportsbook.fanduel.com/navigation/basketball"

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant Global Basketball", page_icon="🌍", layout="wide")
st.title("🌍 Savant Global: Live Pace Scanner")

# --- SIDEBAR: LEAGUE SELECTOR ---
with st.sidebar:
    st.header("🏆 League Selection")
    # Mapping friendly names to Odds API keys
    league_choice = st.selectbox(
        "Choose League",
        ["NBA", "EuroLeague", "CBA (China)", "NBL (Australia)"]
    )
    
    league_map = {
        "NBA": "basketball_nba",
        "EuroLeague": "basketball_euroleague",
        "CBA (China)": "basketball_cba",
        "NBL (Australia)": "basketball_nba_nbl"
    }
    selected_sport = league_map[league_choice]

    st.divider()
    
    st.header("⚙️ Strategy")
    min_edge = st.slider("Min Edge", 1.0, 10.0, 4.0)
    
    if st.button("🚀 SCAN LIVE LEAGUE", type="primary"):
        st.rerun()

# --- ENGINE: FETCH ODDS & LIVE SCORES ---
def fetch_global_data(sport_key):
    # This endpoint pulls BOTH odds and live scores in one go
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={API_KEY}&regions=us&markets=totals&oddsFormat=american"
    score_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/?apiKey={API_KEY}&daysFrom=1"
    
    try:
        # 1. Get Odds
        odds_res = requests.get(url).json()
        # 2. Get Live Scores
        score_res = requests.get(score_url).json()
        
        if 'message' in odds_res:
            st.error(f"API Error: {odds_res['message']}")
            return pd.DataFrame()

        # Create a Score Map: { "Home Team": {"score": 100, "period": 3, "clock": 5} }
        score_map = {s['home_team']: s for s in score_res if s['completed'] == False}

        payload = []
        for game in odds_res:
            home_team = game['home_team']
            away_team = game['away_team']
            
            # Check if game is LIVE (exists in our score map)
            if home_team in score_map:
                live = score_map[home_team]
                
                # Get Scores
                h_score = int(next((s['score'] for s in live['scores'] if s['name'] == home_team), 0))
                a_score = int(next((s['score'] for s in live['scores'] if s['name'] == away_team), 0))
                curr_total = h_score + a_score
                
                # Period/Time Logic (Varies by league)
                # Euro/CBA are 40 min games. NBA is 48.
                game_length = 40 if "nba" not in sport_key else 48
                
                # --- SAVANT PACE LOGIC ---
                # Since free API doesn't give us raw possessions, we use 'Point Velocity'
                # Formula: (Current Points / Minutes Played) * Full Game Minutes
                # Assuming 10 mins per quarter for Euro/CBA
                min_played = 20 # Placeholder: Free API often lags on exact clock. 
                # Better to manually adjust this or use the 'last_update' timestamp.
                
                # --- FETCH FANDUEL LINE ---
                target_book = next((b for b in game['bookmakers'] if b['key'] == 'fanduel'), None)
                if not target_book and game['bookmakers']:
                    target_book = game['bookmakers'][0]
                
                line = 0
                if target_book:
                    for market in target_book['markets']:
                        if market['key'] == 'totals':
                            line = market['outcomes'][0]['point']

                # Savant Projection (Simple Velocity Model)
                # Adjusted for league efficiency (CBA is high, Euro is low)
                efficiency_coeff = 1.15 if "cba" in sport_key else 0.95
                projection = (curr_total * 2.1) * efficiency_coeff # Rough scaling
                
                edge = projection - line if line > 0 else 0

                payload.append({
                    "Matchup": f"{away_team} @ {home_team}",
                    "Live Score": f"{a_score} - {h_score}",
                    "Savant Proj": round(projection, 1),
                    "FanDuel": line,
                    "EDGE": round(edge, 1)
                })

        return pd.DataFrame(payload)

    except Exception as e:
        st.error(f"Connection Error: {e}")
        return pd.DataFrame()

# --- DISPLAY ---
with st.spinner(f"Scanning {league_choice}..."):
    df = fetch_global_data(selected_sport)
    
    if not df.empty:
        def highlight(row):
            if row['EDGE'] >= min_edge:
                return ['background-color: #d4edda; color: #155724'] * len(row)
            elif row['EDGE'] <= -min_edge:
                return ['background-color: #f8d7da; color: #721c24'] * len(row)
            return [''] * len(row)

        st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True)
        
        for _, row in df.iterrows():
            if abs(row['EDGE']) >= min_edge:
                with st.container(border=True):
                    st.write(f"🚨 **{row['Matchup']}**")
                    st.write(f"Proj: {row['Savant Proj']} | Book: {row['FanDuel']} | **Edge: {row['EDGE']}**")
                    st.link_button("💰 OPEN FANDUEL", FANDUEL_URL)
    else:
        st.info(f"No live {league_choice} games found right now. Check back during local game times!")
