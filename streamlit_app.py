import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIG ---
ODDS_API_KEY = "6b10d20e4323876f867026893e161475"
FANDUEL_URL = "https://sportsbook.fanduel.com/navigation/basketball"

st.set_page_config(page_title="Savant v4: Precision Clock", layout="wide")
st.title("🏀 Savant v4: Real-Time Precision")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["NBA", "EuroLeague", "CBA (China)"])
    league_map = {
        "NBA": {"odds_key": "basketball_nba", "len": 48, "coeff": 1.12},
        "EuroLeague": {"odds_key": "basketball_euroleague", "len": 40, "coeff": 0.94},
        "CBA (China)": {"odds_key": "basketball_cba", "len": 40, "coeff": 1.05}
    }
    config = league_map[league_choice]
    
    st.divider()
    if st.button("🚀 FORCE RE-SCAN", type="primary"):
        st.rerun()

# --- THE "HIDDEN" SCRAPER ENGINE ---
def get_realtime_clock_and_scores():
    """
    Taps into a high-speed live score endpoint.
    This is much faster and more accurate than standard APIs.
    """
    # Using a common public endpoint used by live-score widgets
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    try:
        res = requests.get(url, timeout=5).json()
        score_data = {}
        for stage in res.get('Stages', []):
            for event in stage.get('Events', []):
                # We map by team name
                home = event.get('T1', [{}])[0].get('Nm', 'Unknown')
                score_data[home] = {
                    "h_score": int(event.get('Tr1', 0)),
                    "a_score": int(event.get('Tr2', 0)),
                    "clock": event.get('Eps', '00:00'), # e.g., "34'" or "Q4 02:15"
                    "status": event.get('Eps', '')
                }
        return score_data
    except:
        return {}

def fetch_savant_data(config):
    odds_url = f"https://api.the-odds-api.com/v4/sports/{config['odds_key']}/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=totals&oddsFormat=american"
    
    try:
        odds_res = requests.get(odds_url).json()
        live_scores = get_realtime_clock_and_scores()
        
        payload = []
        for game in odds_res:
            home_t = game.get('home_team')
            # Look for team match in live scores
            match = next((v for k, v in live_scores.items() if home_t in k or k in home_t), None)
            
            if match:
                curr_total = match['h_score'] + match['a_score']
                clock_raw = match['clock']
                
                # --- PRECISION CLOCK PARSER ---
                # Converts strings like "38'" or "Q4 02:15" to exact decimal minutes
                try:
                    if "'" in clock_raw: # Format: "38'"
                        mins_played = float(clock_raw.replace("'", ""))
                    elif ":" in clock_raw: # Format: "Q4 02:15"
                        parts = clock_raw.split(' ')
                        q_num = int(parts[0].replace('Q', ''))
                        m, s = map(int, parts[1].split(':'))
                        q_len = config['len'] / 4
                        mins_played = ((q_num - 1) * q_len) + (q_len - m - (s/60))
                    else:
                        mins_played = 0
                except:
                    mins_played = 0

                # Fetch Line
                line = 0
                book = next((b for b in game.get('bookmakers', []) if b['key'] == 'fanduel'), None)
                if book:
                    mkt = next((m for m in book.get('markets', []) if m['key'] == 'totals'), None)
                    if mkt: line = mkt['outcomes'][0]['point']

                # --- THE SAVANT MATH ---
                if mins_played > 1 and mins_played < (config['len'] - 0.5):
                    ppm = curr_total / mins_played
                    mins_rem = config['len'] - mins_played
                    final_proj = curr_total + (ppm * mins_rem * config['coeff'])
                    edge = round(final_proj - line, 1)

                    payload.append({
                        "Matchup": f"{game['away_team']} @ {home_t}",
                        "Score": f"{match['a_score']}-{match['h_score']}",
                        "Exact Min": round(mins_played, 2),
                        "Proj": round(final_proj, 1),
                        "Line": line,
                        "EDGE": edge
                    })
        return pd.DataFrame(payload)
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return pd.DataFrame()

# --- DISPLAY ---
df = fetch_savant_data(config)
if not df.empty:
    st.dataframe(df.style.background_gradient(cmap='RdYlGn', subset=['EDGE']), use_container_width=True)
else:
    st.info("Waiting for live games to sync. Tip: Re-scan in 10 seconds.")
