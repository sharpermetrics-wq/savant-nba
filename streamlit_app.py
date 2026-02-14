import streamlit as st
import pandas as pd
import requests
from apify_client import ApifyClient

# --- SECURE CONFIG ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("Missing APIFY_TOKEN! Check Streamlit Secrets.")
    st.stop()

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v9.0: Raw Feed", layout="wide")
st.title("🏀 Savant Global v9.0: The Unfiltered Feed")

with st.sidebar:
    st.header("⚙️ Controls")
    if st.button("🚀 REFRESH FEED", type="primary"):
        st.rerun()
    
    st.divider()
    st.info("Showing ALL live games. No filters.")

# --- STEP 1: FETCH RAW FEED ---
def get_live_games():
    # The '0.00' endpoint pulls all live games for the current UTC day
    url = "https://prod-public-api.livescore.com/v1/api/react/live/basketball/0.00?MD=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        games = []
        
        if 'Stages' in res:
            for stage in res['Stages']:
                # Capture the raw league name (e.g. "USA - Mid-American Conference")
                league_name = stage.get('Snm', 'Unknown')
                
                for event in stage.get('Events', []):
                    games.append({
                        "league": league_name,
                        "home": event['T1'][0]['Nm'],
                        "away": event['T2'][0]['Nm'],
                        "h_score": int(event.get('Tr1', 0) or 0),
                        "a_score": int(event.get('Tr2', 0) or 0),
                        "clock": str(event.get('Eps', '00:00')),
                        "eid": event.get('Eid')
                    })
        return games
    except Exception as e:
        st.error(f"Feed Error: {e}")
        return []

# --- STEP 2: CALCULATE PROJECTIONS ---
with st.spinner("Pulling global live data..."):
    live_games = get_live_games()
    results = []

    for game in live_games:
        total = game['h_score'] + game['a_score']
        clock = game['clock']
        league = game['league'].upper()
        
        # --- AUTO-DETECT SETTINGS ---
        # NBA games are 48 mins; almost everything else (NCAA, NBB, Euro) is 40 mins
        if "NBA" in league and "G LEAGUE" not in league:
            full_time = 48.0
            coeff = 1.12
        else:
            full_time = 40.0
            coeff = 1.08 # Default to slightly conservative for NCAA/Intl

        # --- UNIVERSAL CLOCK PARSER ---
        try:
            mins_played = 0.0
            
            # Scenario A: Quarters (e.g., "Q3 04:30")
            if "Q" in clock and ":" in clock:
                parts = clock.split(' ')
                q = int(parts[0].replace('Q',''))
                m, s = map(int, parts[-1].split(':'))
                q_len = full_time / 4
                mins_played = ((q-1) * q_len) + (q_len - m - (s/60))

            # Scenario B: Halves (NCAA) - e.g., "14:30 1st Half"
            elif ("1" in clock or "2" in clock) and ":" in clock and "Q" not in clock:
                # NCAA uses count-down from 20:00
                m, s = map(int, clock.split(' ')[0].split(':'))
                if "1" in clock: # 1st Half
                    mins_played = 20 - m - (s/60)
                else: # 2nd Half
                    mins_played = 20 + (20 - m - (s/60))
            
            # Scenario C: Halftime
            elif "HT" in clock or "HALF" in clock:
                mins_played = full_time / 2

            # Only show games that have actually started (more than 2 mins in)
            if mins_played > 2.0:
                proj = (total / mins_played) * full_time * coeff
                
                results.append({
                    "League": game['league'], # Visible so you know where it's coming from
                    "Matchup": f"{game['away']} @ {game['home']}",
                    "Score": f"{game['a_score']}-{game['h_score']}",
                    "Clock": clock,
                    "Proj Total": round(proj, 1)
                })
        except:
            continue

# --- DISPLAY ---
if results:
    # Sort by League to group them nicely
    df = pd.DataFrame(results).sort_values(by="League")
    
    st.success(f"Tracking {len(results)} live games.")
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.warning("No live games found. (If games are scheduled, they may not have tipped off yet).")
    # Debug: Show raw list if empty
    if live_games:
        st.write("Debug - Raw Games Found (but filtered by clock):")
        st.write(live_games)
