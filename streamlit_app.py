import streamlit as st
import pandas as pd
import requests

# --- CONFIGURATION ---
ODDS_API_KEY = "6b10d20e4323876f867026893e161475"
BDL_API_KEY = "5e11f223-5b4b-4b2a-adda-232591ea21e5"
FANDUEL_URL = "https://sportsbook.fanduel.com/navigation/basketball"

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v3: Auto-Clock", page_icon="🏀", layout="wide")
st.title("🏀 Savant v3: Auto-Clock Dashboard")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "CBA (China)"])
    
    # Logic for Game Length & Scoring Efficiency
    league_map = {
        "NBA": {"odds_key": "basketball_nba", "len": 48, "coeff": 1.12},
        "EuroLeague": {"odds_key": "basketball_euroleague", "len": 40, "coeff": 0.94},
        "CBA (China)": {"odds_key": "basketball_cba", "len": 40, "coeff": 1.05}
    }
    config = league_map[league_choice]

    st.divider()
    st.header("🕒 Manual Backup")
    st.caption("If Auto-Clock fails, move this slider to override.")
    manual_time = st.slider("Minutes Played", 0, config['len'], 0)
    
    if st.button("🚀 SCAN LIVE MARKET", type="primary"):
        st.rerun()

# --- ENGINE: FETCH DATA ---
def fetch_live_data(config, manual_val):
    # 1. Fetch FanDuel Odds (The Odds API)
    odds_url = f"https://api.the-odds-api.com/v4/sports/{config['odds_key']}/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=totals&oddsFormat=american"
    
    # 2. Fetch Live Scores & Clock (BallDontLie)
    bdl_url = "https://api.balldontlie.io/v1/games/live"
    headers = {"Authorization": BDL_API_KEY}
    
    try:
        odds_res = requests.get(odds_url).json()
        bdl_res = requests.get(bdl_url, headers=headers).json()
        
        # Map BDL games by team name for easy lookup
        live_games = bdl_res.get('data', [])
        score_map = {g['home_team']['full_name']: g for g in live_games}

        payload = []
        for game in odds_res:
            home_t = game['home_team']
            away_t = game['away_team']
            
            # Fuzzy match team names between APIs
            match = next((v for k, v in score_map.items() if home_t in k or k in home_t), None)
            
            if match:
                h_score = match.get('home_score', 0)
                a_score = match.get('visitor_score', 0)
                curr_total = h_score + a_score
                
                # --- AUTO-CLOCK LOGIC ---
                period = match.get('period', 1)
                time_str = match.get('time', "00:00") # Format "08:22"
                
                try:
                    # Convert "MM:SS" remaining to "Minutes Played"
                    m, s = map(int, time_str.split(':'))
                    quarter_len = config['len'] / 4
                    time_played_in_q = quarter_len - m
                    auto_min_played = ((period - 1) * quarter_len) + time_played_in_q
                except:
                    auto_min_played = 0

                # Priority: Manual Slider > Auto Clock
                final_min_played = manual_val if manual_val > 0 else auto_min_played
                
                # --- GET FANDUEL TOTAL ---
                line = 0
                book = next((b for b in game['bookmakers'] if b['key'] == 'fanduel'), None)
                if not book and game['bookmakers']: book = game['bookmakers'][0]
                
                if book:
                    mkt = next((m for m in book['markets'] if m['key'] == 'totals'), None)
                    if mkt: line = mkt['outcomes'][0]['point']

                # --- SAVANT MATH ---
                if final_min_played > 1: # Need 1 min of data
                    mins_rem = config['len'] - final_min_played
                    ppm = curr_total / final_min_played
                    
                    # Projection = Current + (Current Rate * Remaining Time * Efficiency Coeff)
                    final_proj = curr_total + (ppm * mins_rem * config['coeff'])
                    edge = final_proj - line if line > 0 else 0
                    
                    payload.append({
                        "Matchup": f"{away_t} @ {home_t}",
                        "Score": f"{a_score}-{h_score}",
                        "Clock": f"Q{period} {time_str}",
                        "Savant Proj": round(final_proj, 1),
                        "FanDuel": line,
                        "EDGE": round(edge, 1)
                    })
        return pd.DataFrame(payload)
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# --- DISPLAY ---
with st.spinner("Syncing Live Scores & Odds..."):
    df = fetch_live_data(config, manual_time)

if not df.empty:
    st.success(f"Scanning {len(df)} Live Games")
    
    # Sort by the most actionable edges
    df = df.sort_values(by="EDGE", ascending=False)
    
    st.dataframe(
        df.style.background_gradient(cmap='RdYlGn', subset=['EDGE']),
        use_container_width=True
    )
    
    for _, row in df.iterrows():
        if abs(row['EDGE']) > 3.5:
            direction = "OVER" if row['EDGE'] > 0 else "UNDER"
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.write(f"### 🚨 {direction}: {row['Matchup']}")
                    st.write(f"Savant: **{row['Savant Proj']}** | FanDuel: **{row['FanDuel']}**")
                    st.caption(f"Clock: {row['Clock']} | Calculated edge: {row['EDGE']} points")
                with c2:
                    st.link_button("💰 BET SLIP", FANDUEL_URL, use_container_width=True, type="primary")
else:
    st.info("No live games found for the selected league. Check tip-off times!")
