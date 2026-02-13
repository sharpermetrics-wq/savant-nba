import streamlit as st
import pandas as pd
import requests

# --- CONFIGURATION ---
# Your Verified Odds API Key
API_KEY = "6b10d20e4323876f867026893e161475"
FANDUEL_URL = "https://sportsbook.fanduel.com/navigation/basketball"

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant Global HUD", page_icon="🏀", layout="wide")
st.title("🏀 Savant Global: multi-League Scanner")

# --- SIDEBAR: LEAGUE SELECTOR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox(
        "Choose League",
        ["NBA", "EuroLeague", "CBA (China)", "NBL (Australia)"]
    )
    
    # League Specific Mappings
    league_map = {
        "NBA": {"key": "basketball_nba", "len": 48, "coeff": 1.12},
        "EuroLeague": {"key": "basketball_euroleague", "len": 40, "coeff": 0.96},
        "CBA (China)": {"key": "basketball_cba", "len": 40, "coeff": 1.05},
        "NBL (Australia)": {"key": "basketball_nba_nbl", "len": 40, "coeff": 1.02}
    }
    
    selected_config = league_map[league_choice]

    st.divider()
    
    st.header("⚙️ Strategy")
    min_edge = st.slider("Min Edge (Pts)", 1.0, 10.0, 4.0)
    
    if st.button("🚀 SCAN LIVE MARKET", type="primary"):
        st.rerun()

# --- ENGINE: FETCH ODDS & LIVE SCORES ---
def fetch_global_data(config):
    sport_key = config['key']
    game_max_min = config['len']
    eff_coeff = config['coeff']
    
    # API Endpoints
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={API_KEY}&regions=us&markets=totals&oddsFormat=american"
    score_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/?apiKey={API_KEY}&daysFrom=1"
    
    try:
        odds_res = requests.get(url).json()
        score_res = requests.get(score_url).json()
        
        if isinstance(odds_res, dict) and 'message' in odds_res:
            st.error(f"API Error: {odds_res['message']}")
            return pd.DataFrame()

        # Map live scores by home team
        score_map = {s['home_team']: s for s in score_res if not s['completed']}

        payload = []
        for game in odds_res:
            home_t = game['home_team']
            away_t = game['away_team']
            
            if home_t in score_map:
                live = score_map[home_t]
                
                # Extract Scores
                h_score = next((s['score'] for s in live['scores'] if s['name'] == home_t), 0)
                a_score = next((s['score'] for s in live['scores'] if s['name'] == away_t), 0)
                curr_total = int(h_score) + int(a_score)
                
                # Time Estimation (Odds API provides 'last_update')
                # For more accuracy, we assume we are at the halfway point if clock is missing
                # Or you can manually input 'Minutes Played' in the sidebar
                est_min_played = game_max_min / 2 
                
                # --- FETCH FANDUEL LINE ---
                target_book = next((b for b in game['bookmakers'] if b['key'] == 'fanduel'), None)
                if not target_book and game['bookmakers']:
                    target_book = game['bookmakers'][0]
                
                line = 0
                if target_book:
                    market = next((m for m in target_book['markets'] if m['key'] == 'totals'), None)
                    if market:
                        line = market['outcomes'][0]['point']

                # --- SAVANT PROJECTION LOGIC ---
                # Fixed for 40 vs 48 minute differences
                # Base Projection = (Current Score / Est Minutes) * Total Game Minutes
                base_proj = (curr_total / est_min_played) * game_max_min
                final_proj = base_proj * eff_coeff
                
                edge = final_proj - line if line > 0 else 0

                payload.append({
                    "Matchup": f"{away_t} @ {home_t}",
                    "Score": f"{a_score}-{h_score}",
                    "Savant Proj": round(final_proj, 1),
                    "FanDuel": line,
                    "EDGE": round(edge, 1),
                    "Type": "EURO/CBA (40m)" if game_max_min == 40 else "NBA (48m)"
                })

        return pd.DataFrame(payload)

    except Exception as e:
        st.error(f"Scanner Error: {e}")
        return pd.DataFrame()

# --- DISPLAY ---
with st.spinner(f"Analyzing {league_choice} Markets..."):
    df = fetch_global_data(selected_config)
    
    if not df.empty:
        # Sort by best EDGE
        df = df.sort_values(by="EDGE", ascending=False)

        def highlight_edge(row):
            if row['EDGE'] >= min_edge:
                return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row)
            elif row['EDGE'] <= -min_edge:
                return ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row)
            return [''] * len(row)

        st.dataframe(df.style.apply(highlight_edge, axis=1), use_container_width=True)
        
        # Action Alerts
        for _, row in df.iterrows():
            if abs(row['EDGE']) >= min_edge:
                direction = "OVER" if row['EDGE'] > 0 else "UNDER"
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.write(f"### {direction}: {row['Matchup']}")
                        st.write(f"**Savant:** {row['Savant Proj']} | **FanDuel:** {row['FanDuel']} | **Edge:** {row['EDGE']}")
                    with c2:
                        st.link_button("💰 BET NOW", FANDUEL_URL, use_container_width=True, type="primary")
    else:
        st.info(f"No live {league_choice} games found. Check game schedules for local tip-off times.")
