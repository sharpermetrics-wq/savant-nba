import streamlit as st
import pandas as pd
import requests

# --- CONFIG ---
ODDS_API_KEY = "6b10d20e4323876f867026893e161475"
BDL_API_KEY = "5e11f223-5b4b-4b2a-adda-232591ea21e5"
FANDUEL_URL = "https://sportsbook.fanduel.com/navigation/basketball"

st.set_page_config(page_title="Savant v3.1: Bulletproof", layout="wide")
st.title("🏀 Savant Global HUD")

with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "CBA (China)"])
    league_map = {
        "NBA": {"odds_key": "basketball_nba", "len": 48, "coeff": 1.12},
        "EuroLeague": {"odds_key": "basketball_euroleague", "len": 40, "coeff": 0.94},
        "CBA (China)": {"odds_key": "basketball_cba", "len": 40, "coeff": 1.05}
    }
    config = league_map[league_choice]
    
    st.divider()
    manual_time = st.slider("Manual Clock Override", 0, config['len'], 0)
    if st.button("🚀 SCAN NOW", type="primary"):
        st.rerun()

def fetch_data(config, manual_val):
    # 1. Fetch Odds
    odds_url = f"https://api.the-odds-api.com/v4/sports/{config['odds_key']}/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=totals&oddsFormat=american"
    # 2. Fetch Scores
    bdl_url = "https://api.balldontlie.io/v1/games/live"
    headers = {"Authorization": BDL_API_KEY}
    
    try:
        odds_res = requests.get(odds_url).json()
        bdl_res = requests.get(bdl_url, headers=headers).json()
        
        # FIX: Check if bdl_res is a dictionary and has 'data' key
        if not isinstance(bdl_res, dict) or 'data' not in bdl_res:
            st.error(f"BallDontLie API error: {bdl_res}")
            return pd.DataFrame()
            
        live_games = bdl_res['data']
        # Map by Team Name
        score_map = {}
        for g in live_games:
            # Safely get team name
            home_name = g.get('home_team', {}).get('full_name', 'Unknown')
            score_map[home_name] = g

        payload = []
        for game in odds_res:
            # Safely check if game is a dictionary
            if not isinstance(game, dict): continue
            
            home_t = game.get('home_team')
            away_t = game.get('away_team')
            
            # Match game with score
            match = next((v for k, v in score_map.items() if home_t in k or k in home_t), None)
            
            if match:
                h_score = match.get('home_score', 0)
                a_score = match.get('visitor_score', 0)
                curr_total = h_score + a_score
                
                # Time Logic
                period = match.get('period', 1)
                time_str = str(match.get('time', "00:00"))
                
                auto_min_played = 0
                if ":" in time_str:
                    try:
                        m, s = map(int, time_str.split(':'))
                        q_len = config['len'] / 4
                        auto_min_played = ((period - 1) * q_len) + (q_len - m)
                    except: pass

                final_min_played = manual_val if manual_val > 0 else auto_min_played
                
                # Get Odds
                line = 0
                book = next((b for b in game.get('bookmakers', []) if b['key'] == 'fanduel'), None)
                if not book and game.get('bookmakers'): book = game['bookmakers'][0]
                if book:
                    mkt = next((m for m in book.get('markets', []) if m['key'] == 'totals'), None)
                    if mkt: line = mkt['outcomes'][0]['point']

                if final_min_played > 1:
                    ppm = curr_total / final_min_played
                    mins_rem = config['len'] - final_min_played
                    final_proj = curr_total + (ppm * mins_rem * config['coeff'])
                    edge = round(final_proj - line, 1) if line > 0 else 0
                    
                    payload.append({
                        "Matchup": f"{away_t} @ {home_t}",
                        "Score": f"{a_score}-{h_score}",
                        "Clock": f"Q{period} {time_str}",
                        "Savant Proj": round(final_proj, 1),
                        "FanDuel": line,
                        "EDGE": edge
                    })
        return pd.DataFrame(payload)
    except Exception as e:
        st.error(f"System Error: {e}")
        return pd.DataFrame()

df = fetch_data(config, manual_time)
if not df.empty:
    st.dataframe(df.style.background_gradient(cmap='RdYlGn', subset=['EDGE']), use_container_width=True)
else:
    st.info("No live games matched between Odds and Scores. Check the Clock Slider or League choice.")
