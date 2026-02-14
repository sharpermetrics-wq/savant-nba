import streamlit as st
import pandas as pd
import requests
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v28: Fixed & Loaded", layout="wide")
st.title("🏀 Savant v28: The 'Sticky' Dashboard")

# --- MEMORY BANK (Session State) ---
# This saves your manual lines so they don't vanish on refresh
if 'sticky_lines' not in st.session_state:
    st.session_state.sticky_lines = {} 

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    # The "Action" Button
    if st.button("🔄 UPDATE SCORE & CLOCK", type="primary"):
        st.rerun()
        
    st.divider()
    st.info("ℹ️ **Instructions:** If a line is missing, type it in. The app will REMEMBER it for the rest of the game.")

# --- HELPER: REGEX FOR ODDS ---
def extract_total(text):
    try:
        # Looks for "O/U 145.5" or just "145.5" in text blobs
        match = re.search(r'O/U\s*(\d{3}\.?\d*)', str(text), re.IGNORECASE)
        if match: return float(match.group(1))
        return 0.0
    except: return 0.0

# --- STEP 1: FETCH DATA (ESPN) ---
def fetch_game_data(league):
    ts = int(time.time()) # Anti-cache timestamp
    if league == "NBA":
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100&t={ts}"
    else:
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000&t={ts}"
    
    try:
        headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
        res = requests.get(url, headers=headers, timeout=8).json()
        
        games = []
        for event in res.get('events', []):
            if event['status']['type']['state'] == 'in':
                comp = event['competitions'][0]
                
                # --- ODDS SCRAPER (The Kitchen Sink) ---
                api_line = 0.0
                if 'odds' in comp:
                    for odd in comp['odds']:
                        # Try text scrape
                        if 'details' in odd:
                            val = extract_total(odd['details'])
                            if val > 100: api_line = val
                        # Try numeric field
                        if api_line == 0.0 and 'overUnder' in odd:
                            try:
                                val = float(odd['overUnder'])
                                if val > 100: api_line = val
                            except: pass
                
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_display": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home": int(comp['competitors'][0]['score']),
                    "away": int(comp['competitors'][1]['score']),
                    "api_line": api_line
                })
        return games
    except: return []

# --- STEP 2: DEEP STATS (The Pace Engine) ---
def fetch_deep_stats(game_id, league):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    
    data = {"fouls":0, "pace_stats": {"fga":0, "fta":0, "orb":0, "tov":0}, "deep_line": 0.0}
    try:
        res = requests.get(url, timeout=4).json()
        
        # A. PARSE BOX SCORE
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                for stat in team.get('statistics', []):
                    val = 0.0
                    try:
                        raw = stat.get('displayValue','0')
                        val = float(raw.split('-')[1]) if '-' in raw else float(raw)
                    except: val = 0.0
                    
                    nm = stat.get('name','').lower() # API Key Name
                    
                    # Accumulate Stats
                    if "foul" in nm: data['fouls'] += val
                    if "fieldgoal" in nm: data['pace_stats']['fga'] += val
                    if "freethrow" in nm: data['pace_stats']['fta'] += val
                    if "offensive" in nm: data['pace_stats']['orb'] += val
                    if "turnover" in nm: data['pace_stats']['tov'] += val
        
        # B. BACKUP ODDS (PickCenter)
        if 'pickcenter' in res:
            for p in res['pickcenter']:
                if 'overUnder' in p:
                    try:
                        v = float(p['overUnder'])
                        if v > 100: 
                            data['deep_line'] = v
                            break
                    except: continue
        return data
    except: return data

# --- STEP 3: EXECUTION ---
with st.spinner("Syncing Live Data..."):
    live_games = fetch_game_data(league_choice)

if not live_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress = st.progress(0)
    results = []
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    for i, game in enumerate(live_games):
        progress.progress((i + 1) / len(live_games))
        
        # 1. CLOCK MATH
        try:
            if ":" in game['clock_display']: m, s = map(int, game['clock_display'].split(':'))
            else: m, s = 0, 0
            
            p = game['period']
            mins = 0.0
            if league_choice == "NBA":
                if p <= 4: mins = ((p-1)*12) + (12 - m - (s/60))
                else: mins = 48.0 + ((p-4)*5) - m - (s/60)
            else: 
                if p == 1: mins = 20.0 - m - (s/60)
                elif p == 2: mins = 20.0 + (20.0 - m - (s/60))
                else: mins = 40.0 + ((p-2)*5) - m - (s/60)
        except: mins = 0.0

        if mins > 2.0:
            # 2. GET DEEP STATS
            deep = fetch_deep_stats(game['id'], league_choice)
            
            # 3. LINE LOGIC (Sticky)
            # Check 1: API Line
            current_line = game['api_line']
            if current_line == 0.0: current_line = deep['deep_line']
            
            # Check 2: Memory (Did user edit this?)
            saved_line = st.session_state.sticky_lines.get(game['id'], 0.0)
            
            # Decision: Use Saved if API is 0, or if User Saved an Override
            final_line = 0.0
            if saved_line > 0:
                final_line = saved_line # User edit overrides all
            elif current_line > 0:
                final_line = current_line
                # Auto-save valid API lines to memory so they stick
                st.session_state.sticky_lines[game['id']] = final_line
            
            # 4. SAVANT MATH
            total = game['home'] + game['away']
            
            # Pace Metrics
            fpm = deep['fouls'] / mins
            stats = deep['pace_stats']
            poss = stats['fga'] - stats['orb'] + stats['tov'] + (0.44 * stats['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            # Projection
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            edge = round(proj - final_line, 1) if final_line > 0 else -999.0
            
            # Formatting
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")
            
            results.append({
                "ID": game['id'], # For tracking edits
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": f"{p_str} {game['clock_display']}",
                "Fouls": int(deep['fouls']),
                "Pace": round(pace * FULL_TIME, 1), # Game Pace
                "FPM": round(fpm, 2),
                "Line": final_line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge
            })

    progress.empty()

    if results:
        df = pd.DataFrame(results)
        
        # Sort by Edge Magnitude
        df['sort_val'] = df['EDGE'].apply(lambda x: abs(x) if x != -999 else 0)
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])
        
        # --- EDITABLE DASHBOARD ---
        st.markdown("### 📊 Live Dashboard")
        
        edited_df = st.data_editor(
            df,
            column_config={
                "Line": st.column_config.NumberColumn("Line (Edit)", required=True, format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Fouls": st.column_config.NumberColumn("Fouls", format="%d"),
                "Pace": st.column_config.NumberColumn("Pace", format="%.1f"),
                "FPM": st.column_config.NumberColumn("FPM", format="%.2f"),
                "ID": None # Hide ID
            },
            disabled=["Matchup", "Score", "Time", "Fouls", "Pace", "FPM", "Savant Proj", "EDGE"],
            use_container_width=True,
            hide_index=True,
            key="dashboard_editor"
        )
        
        # --- SAVE EDITS TO MEMORY ---
        for index, row in edited_df.iterrows():
            g_id = row['ID']
            new_line = row['Line']
            
            # If user typed a new line, save it to session state
            if new_line > 0 and new_line != st.session_state.sticky_lines.get(g_id):
                st.session_state.sticky_lines[g_id] = new_line
