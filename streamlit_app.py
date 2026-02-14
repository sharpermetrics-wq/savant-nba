import streamlit as st
import pandas as pd
from apify_client import ApifyClient

# --- SECURE CONFIG ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("Missing APIFY_TOKEN in Secrets!")
    st.stop()

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v6.1: Direct Injection", layout="wide")
st.title("🏀 Savant v6.1: Pro Hybrid HUD")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["Brazil NBB", "CBA (China)", "NBA", "EuroLeague"])
    
    # Savant Global Coefficients & Rules
    league_map = {
        "Brazil NBB": {"len": 40, "coeff": 1.02, "auto": False, "val": "BRAZIL"},
        "CBA (China)": {"len": 40, "coeff": 1.05, "auto": False, "val": "CHINA"},
        "NBA": {"len": 48, "coeff": 1.12, "auto": True, "val": "NBA"},
        "EuroLeague": {"len": 40, "coeff": 0.94, "auto": True, "val": "UCL"}
    }
    config = league_map[league_choice]

    st.divider()
    if config["auto"]:
        st.info(f"Automation is ACTIVE for {league_choice}.")
    else:
        st.warning(f"Manual Injection Mode for {league_choice}.")

# --- STEP 1: AUTOMATED ODDS (NBA/EURO ONLY) ---
def get_auto_odds(league_val):
    if not config["auto"]: return {}
    client = ApifyClient(APIFY_TOKEN)
    try:
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input={"league": league_val, "sportsbook": "FanDuel"})
        return {item['homeTeam']: item['odds'][0]['overUnder'] for item in client.dataset(run["defaultDatasetId"]).iterate_items() if item.get('odds')}
    except: return {}

# --- STEP 2: MANUAL INJECTION UI (NBB/CBA) ---
if not config["auto"]:
    st.subheader(f"📊 {league_choice} Savant Calculator")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        h_score = st.number_input("Home Score", min_value=0, value=65)
        a_score = st.number_input("Away Score", min_value=0, value=58)
    with col2:
        q_current = st.selectbox("Current Quarter", [1, 2, 3, 4])
        time_left = st.text_input("Clock (MM:SS)", "05:00")
    with col3:
        live_line = st.number_input("FanDuel Live Line", min_value=0.0, value=165.5, step=0.5)

    # Calculation logic
    try:
        m, s = map(int, time_left.split(':'))
        q_len = config['len'] / 4
        mins_played = ((q_current - 1) * q_len) + (q_len - m - (s/60))
        
        if mins_played > 0:
            total_now = h_score + a_score
            ppm = total_now / mins_played
            proj = total_now + (ppm * (config['len'] - mins_played) * config['coeff'])
            edge = proj - live_line
            
            # Results HUD
            st.divider()
            r1, r2, r3 = st.columns(3)
            r1.metric("SAVANT PROJ", round(proj, 1))
            r2.metric("EDGE", round(edge, 1), delta=round(edge, 1))
            r3.metric("ELAPSED", f"{round(mins_played, 1)}m")
            
            if abs(edge) >= 4.0:
                st.success(f"🚨 **SIGNAL**: {'OVER' if edge > 0 else 'UNDER'} (Edge: {round(edge,1)})")
    except:
        st.error("Format clock as MM:SS (e.g., 08:30)")

# --- STEP 3: AUTOMATED HUD (NBA/EURO) ---
else:
    with st.spinner(f"Auto-Syncing {league_choice}..."):
        # Since automation is for NBA/Euro, we pull from our standard source
        # (This section would contain the previous auto-sync logic we built)
        st.info("Displaying automated feed for major leagues...")
        # [The automated score/odds logic from v5.9 goes here]

st.divider()
st.caption("Savant v6.1 | Direct Injection Engine | Sharper Metrics")
