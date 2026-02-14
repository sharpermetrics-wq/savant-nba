import streamlit as st
import pandas as pd
import requests

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v10: Stealth", layout="wide")
st.title("🏀 Savant v10: The Stealth Engine")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Math Settings")
    mode = st.radio("Game Type", ["College (40m)", "NBA (48m)", "Intl (40m)"])
    if "NBA" in mode:
        FULL_TIME = 48.0
        COEFF = 1.12
    else:
        FULL_TIME = 40.0
        COEFF = 1.08 # Conservative for College/Intl

    if st.button("🚀 REFRESH FEED", type="primary"):
        st.rerun()

# --- STEP 1: THE STEALTH REQUEST ---
def get_live_games():
    # 1. The URL
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    
    # 2. THE DISGUISE (Headers)
    # This makes the server think we are a real user, not a bot.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://www.livescore.com/',
        'Origin': 'https://www.livescore.com',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        # Check if they blocked us (Status 403 or 429)
        if response.status_code != 200:
            st.error(f"Server Blocked Request (Status: {response.status_code})")
            return None
            
        return response.json()
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

# --- STEP 2: THE PROCESSOR ---
feed_data = get_live_games()
found_games = []

if feed_data and 'Stages' in feed_data:
    for stage in feed_data['Stages']:
        league = stage.get('Snm', 'Unknown')
        for event in stage.get('Events', []):
            found_games.append({
                "League": league,
                "Matchup": f"{event['T1'][0]['Nm']} vs {event['T2'][0]['Nm']}",
                "Score": f"{event.get('Tr1',0)}-{event.get('Tr2',0)}",
                "Total": int(event.get('Tr1',0) or 0) + int(event.get('Tr2',0) or 0),
                "Clock": str(event.get('Eps', '00:00'))
            })

# --- STEP 3: DISPLAY OR FALLBACK ---
if found_games:
    # 3A. AUTOMATED MODE
    st.success(f"Tracking {len(found_games)} Live Games")
    
    # Simple Table
    df = pd.DataFrame(found_games)
    st.dataframe(df, use_container_width=True, hide_index=True)

else:
    # 3B. MANUAL WAR ROOM (The Failsafe)
    st.warning("⚠️ API Feed is blocked or empty. Switched to Manual Mode.")
    st.info("Input the score from your TV to get the Savant Projection instantly.")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        score_now = st.number_input("Current Total Score", value=140, step=1)
    with c2:
        # Easy Time Input
        time_str = st.text_input("Time Left (e.g. 10:00)", "10:00")
        period = st.selectbox("Period", ["1st Half", "2nd Half", "Q1", "Q2", "Q3", "Q4"])
    with c3:
        live_line = st.number_input("Bookie Line", value=155.5)

    # Manual Math Engine
    mins_played = 0.0
    try:
        m, s = map(int, time_str.split(':'))
        
        if "NBA" in mode: # Quarters
            q_len = 12.0
            q_map = {"Q1":1, "Q2":2, "Q3":3, "Q4":4}
            curr_q = q_map.get(period, 1)
            mins_played = ((curr_q - 1) * q_len) + (q_len - m - (s/60))
        else: # College/Intl (Halves or Quarters)
            if "Half" in period:
                half_len = 20.0
                if "1st" in period: mins_played = 20 - m - (s/60)
                else: mins_played = 20 + (20 - m - (s/60))
            else: # Quarters for NBB/Euro
                q_len = 10.0
                q_map = {"Q1":1, "Q2":2, "Q3":3, "Q4":4}
                curr_q = q_map.get(period, 1)
                mins_played = ((curr_q - 1) * q_len) + (q_len - m - (s/60))

    except: mins_played = 0.0

    if mins_played > 1.0:
        proj = (score_now / mins_played) * FULL_TIME * COEFF
        edge = proj - live_line
        
        st.divider()
        col_res1, col_res2 = st.columns(2)
        with col_res1:
            st.metric("SAVANT PROJECTION", f"{round(proj, 1)}")
        with col_res2:
            st.metric("EDGE", f"{round(edge, 1)}", delta_color="normal")
            
        if edge > 4: st.success("🔥 STRONG OVER")
        elif edge < -4: st.error("❄️ STRONG UNDER")
