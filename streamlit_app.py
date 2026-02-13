import streamlit as st
import pandas as pd
import random
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant NBA (SIM MODE)", page_icon="🏀", layout="wide")
st.title("🏀 Savant NBA: Simulation Mode")
st.markdown("### *Testing UI during All-Star Break*")

# --- SIDEBAR: SETTINGS ---
with st.sidebar:
    st.header("⚙️ Simulation Settings")
    min_edge = st.slider("Min Edge to Bet", 1.0, 10.0, 4.0)
    
    st.divider()
    
    if st.button("🔄 GENERATE NEW SIMULATION", type="primary"):
        st.rerun()
    
    st.info("⚠️ This mode uses FAKE data to test your layout.")

# --- FUNCTION: GENERATE FAKE DATA ---
def get_mock_data():
    # Create fake scenarios to test different alerts
    mock_games = [
        # SCENARIO 1: Big EDGE OVER (Green Alert)
        {"home": "LAL", "away": "BOS", "q": 4, "time": 5, "pace": 110.5, "fouls": 2.8, "book": 220.5},
        
        # SCENARIO 2: Big EDGE UNDER (Red Alert)
        {"home": "NYK", "away": "MIA", "q": 3, "time": 10, "pace": 92.0, "fouls": 1.1, "book": 215.0},
        
        # SCENARIO 3: No Edge (Gray - Market is Sharp)
        {"home": "GSW", "away": "PHX", "q": 2, "time": 2, "pace": 102.0, "fouls": 1.9, "book": 228.0},
        
        # SCENARIO 4: Tight Whistle Bonus
        {"home": "DAL", "away": "OKC", "q": 4, "time": 8, "pace": 105.0, "fouls": 2.5, "book": 225.0}
    ]
    
    live_payload = []
    
    for g in mock_games:
        # 1. Fake Logic
        pace = g['pace']
        fpm = g['fouls']
        
        # 2. Fake Projection (Pace * 2.1 is rough approx for total points)
        # Add random noise so it changes every time you click refresh
        noise = random.uniform(-2, 2)
        
        # Ref Bonus: If fouls > 2.1, add 4 points
        ref_boost = 4.0 if fpm > 2.1 else 0
        
        proj = (pace * 2.15) + ref_boost + noise
        
        # 3. Calculate Edge
        edge = proj - g['book']

        live_payload.append({
            "Matchup": f"{g['away']} @ {g['home']}",
            "Qtr": g['q'],
            "Min": g['time'],
            "Pace": round(pace, 1),
            "Fouls/Min": round(fpm, 2),
            "Ref Mode": "🔒 TIGHT" if fpm > 2.1 else "🔓 LOOSE",
            "Savant Proj": round(proj, 1),
            "FanDuel Line": g['book'],
            "EDGE": round(edge, 1)
        })

    return pd.DataFrame(live_payload)

# --- MAIN APP EXECUTION ---
with st.spinner("Simulating Live Games..."):
    # 1. Get Mock Data
    df = get_mock_data()
    
    # 2. Display Table
    if not df.empty:
        # Styling Logic
        def highlight(row):
            if row['EDGE'] >= min_edge:
                return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row) # Green
            elif row['EDGE'] <= -min_edge:
                return ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row) # Red
            return [''] * len(row)

        st.success("Simulation Active: 4 Mock Games Loaded")
        
        st.dataframe(
            df.style.apply(highlight, axis=1).format({
                "Pace": "{:.1f}", 
                "Savant Proj": "{:.1f}", 
                "FanDuel Line": "{:.1f}", 
                "EDGE": "{:.1f}"
            }), 
            use_container_width=True
        )
        
        # 3. Alerts Section
        st.divider()
        st.subheader("📢 Active Alerts")
        
        for _, row in df.iterrows():
            if abs(row['EDGE']) >= min_edge:
                direction = "OVER" if row['EDGE'] > 0 else "UNDER"
                
                if direction == "OVER":
                    st.success(f"**BET OVER: {row['Matchup']}**")
                else:
                    st.error(f"**BET UNDER: {row['Matchup']}**")
                    
                st.write(f"Proj: **{row['Savant Proj']}** vs Line: **{row['FanDuel Line']}** (Edge: {row['EDGE']})")
                
                if "TIGHT" in row['Ref Mode'] and direction == "OVER":
                     st.caption("➕ **Ref Factor:** High Fouls (Tight Whistle detected)")
                st.markdown("---")
