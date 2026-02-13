import streamlit as st
import pandas as pd
import random

# --- CONFIGURATION ---
API_KEY = "6b10d20e4323876f867026893e161475"
# FanDuel deep link for NBA
FANDUEL_NBA_URL = "https://sportsbook.fanduel.com/navigation/nba"

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant NBA (FanDuel)", page_icon="🏀", layout="wide")
st.title("🏀 Savant NBA: FanDuel Edition")

# --- SIDEBAR: SETTINGS ---
with st.sidebar:
    st.header("⚙️ Strategy")
    min_edge = st.slider("Min Edge to Bet", 1.0, 10.0, 4.0)
    
    st.divider()
    
    if st.button("🚀 SCAN FANDUEL LIVE", type="primary"):
        st.rerun()
    
    st.info("⚠️ Simulation Mode Active (All-Star Break)")

# --- MOCK DATA ENGINE ---
def get_mock_data():
    mock_games = [
        {"home": "LAL", "away": "BOS", "pace": 110.5, "fouls": 2.8, "book": 222.5},
        {"home": "NYK", "away": "MIA", "pace": 92.0, "fouls": 1.1, "book": 210.0},
        {"home": "TOR", "away": "PHI", "pace": 104.0, "fouls": 2.4, "book": 218.5}
    ]
    
    data = []
    for g in mock_games:
        # Savant Math
        ref_boost = 4.5 if g['fouls'] > 2.1 else 0
        proj = (g['pace'] * 2.12) + ref_boost + random.uniform(-3, 3)
        edge = proj - g['book']

        data.append({
            "Matchup": f"{g['away']} @ {g['home']}",
            "Pace": round(g['pace'], 1),
            "Fouls/Min": round(g['fouls'], 2),
            "Ref Mode": "🔒 TIGHT" if g['fouls'] > 2.1 else "🔓 LOOSE",
            "Savant Proj": round(proj, 1),
            "FanDuel Line": g['book'],
            "EDGE": round(edge, 1)
        })
    return pd.DataFrame(data)

# --- MAIN APP EXECUTION ---
with st.spinner("Checking FanDuel Lines..."):
    df = get_mock_data()
    
    if not df.empty:
        # Main Table Styling
        def highlight_edge(row):
            if row['EDGE'] >= min_edge:
                return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row)
            elif row['EDGE'] <= -min_edge:
                return ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row)
            return [''] * len(row)

        st.dataframe(df.style.apply(highlight_edge, axis=1), use_container_width=True)
        
        # --- ALERTS & DEEP LINKS ---
        st.divider()
        st.subheader("📢 Live Betting Alerts")
        
        # Display as cards for better mobile view on Pixel 9 Pro
        for _, row in df.iterrows():
            if abs(row['EDGE']) >= min_edge:
                direction = "OVER" if row['EDGE'] > 0 else "UNDER"
                
                # Container for the alert
                with st.container(border=True):
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        st.markdown(f"### {direction}: {row['Matchup']}")
                        st.write(f"**Proj:** {row['Savant Proj']} | **Line:** {row['FanDuel Line']}")
                        st.write(f"**Edge:** {row['EDGE']} pts")
                        if "TIGHT" in row['Ref Mode']:
                            st.caption("🔥 Ref Factor: Tight Whistle (Boosted Efficiency)")
                    
                    with col2:
                        # Deep Link Button
                        # This opens the FanDuel NBA page directly
                        st.link_button(
                            label=f"💰 BET {direction}",
                            url=FANDUEL_NBA_URL,
                            use_container_width=True,
                            type="primary" if direction == "OVER" else "secondary"
                        )
    else:
        st.info("No games currently meet your edge criteria.")
