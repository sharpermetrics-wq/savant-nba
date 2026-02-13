import streamlit as st
import pandas as pd
import requests

# --- CONFIG ---
ODDS_API_KEY = "6b10d20e4323876f867026893e161475"
FANDUEL_URL = "https://sportsbook.fanduel.com/navigation/basketball"

st.set_page_config(page_title="Savant v4.1: Pro HUD", layout="wide")
st.title("🏀 Savant Global: Precision HUD")

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
    if st.button("🚀 FORCE RE-SCAN", type="primary"):
        st.rerun()

def get_precision_scores():
    """
    New Hybrid Scraper: Uses Browser Headers to prevent 'string' errors.
    """
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # Verify we got JSON and not an error string
        if response.status_code != 200: return {}
        data = response.json()
        
        score_data = {}
        if isinstance(data, dict) and 'Stages' in data:
            for stage in data['Stages']:
                for event in stage.get('Events', []):
                    home = event.get('T1', [{}])[0].get('Nm', 'Unknown')
                    score_data[home] = {
                        "h_score": int(event.get('Tr1', 0)) if event.get('Tr1') else 0,
                        "a_score": int(event.get('Tr2', 0)) if event.get('Tr2') else 0,
                        "clock": str(event.get('Eps', '00:00'))
                    }
        return score_data
    except:
        return {}

def fetch_savant_data(config):
    odds_url = f"https://api.the-odds-api.com/v4/sports/{config['odds_key']}/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=totals&oddsFormat=american"
    
    try:
        odds_res = requests.get(odds_url).json()
        live_scores = get_precision_scores()
        
        payload = []
        # Error check: ensure odds_res is a list
        if not isinstance(odds_res, list): return pd.DataFrame()

        for game in odds_res:
            home_t = game.get('home_team')
            match = next((v for k, v in live_scores.items() if home_t in k or k in home_t), None)
            
            if match:
                curr_total = match['h_score'] + match['a_score']
                clock_raw = match['clock']
                
                # PARSER
                try:
                    if "'" in clock_raw:
                        mins_played = float(clock_raw.replace("'", ""))
                    elif ":" in clock_raw:
                        parts = clock_raw.split(' ')
                        q_num = int(parts[0].replace('Q', '')) if 'Q' in parts[0] else 1
                        m_str = parts[1] if len(parts) > 1 else parts[0]
                        m, s = map(int, m_str.split(':'))
                        q_len = config['len'] / 4
                        mins_played = ((q_num - 1) * q_len) + (q_len - m - (s/60))
                    else: mins_played = 0
                except: mins_played = 0

                # Odds Lookup
                line = 0
                book = next((b for b in game.get('bookmakers', []) if b['key'] == 'fanduel'), None)
                if book:
                    mkt = next((m for m in book.get('markets', []) if m['key'] == 'totals'), None)
                    if mkt: line = mkt['outcomes'][0]['point']

                if 2 < mins_played < (config['len'] - 0.5):
                    ppm = curr_total / mins_played
                    mins_rem = config['len'] - mins_played
                    final_proj = curr_total + (ppm * mins_rem * config['coeff'])
                    edge = round(final_proj - line, 1)

                    payload.append({
                        "Matchup": f"{game['away_team']} @ {home_t}",
                        "Score": f"{match['a_score']}-{match['h_score']}",
                        "Clock": clock_raw,
                        "Proj": round(final_proj, 1),
                        "Line": line,
                        "EDGE": edge
                    })
        return pd.DataFrame(payload)
    except:
        return pd.DataFrame()

# --- RUN ---
df = fetch_savant_data(config)
if not df.empty:
    st.dataframe(df.style.background_gradient(cmap='RdYlGn', subset=['EDGE']), use_container_width=True)
else:
    st.info(f"No LIVE {league_choice} games found. Note: CBA is currently on a FIBA break until late February.")
