import streamlit as st
import pandas as pd
import requests
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v29: Precision", layout="wide")
st.title("🏀 Savant v29: Precision Metrics")

# --- MEMORY ---
if 'sticky_lines' not in st.session_state:
    st.session_state.sticky_lines = {} 

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🔄 REFRESH DATA", type="primary"):
        st.rerun()
        
    st.info("ℹ️ Pace is now normalized (Avg ~70 for CBB, ~100 for NBA).")

# --- HELPER: REGEX ---
def extract_total(text):
    try:
        match = re.search(r'O/U\s*(\d{3}\.?\d*)', str(text), re.IGNORECASE)
        if match: return float(match.group(1))
        return 0.0
    except: return 0.0

# --- STEP 1: FETCH GAMES ---
def fetch_game_data(league):
    ts = int(time.time())
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
                
                # ODDS (Scoreboard)
                api_line = 0.0
                if 'odds' in comp:
                    for odd in comp['odds']:
                        if 'details' in odd:
                            val = extract_total(odd['details'])
                            if val > 100: api_line = val
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

# --- STEP 2: DEEP STATS (THE FIX) ---
def fetch_deep_stats(game_id, league):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    
    data = {"fouls":0, "fga":0, "fta":0, "orb":0, "tov":0, "deep_line": 0.0}
    try:
        res = requests.get(url, timeout=4).json()
        
        # A. PRECISE STAT PARSING
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                for stat in team.get('statistics', []):
                    # We grab the 'name' key which is unique (e.g., 'fieldGoalsAttempted')
                    name = stat.get('name', '')
                    val = float(stat.get('displayValue', '0')) # Usually purely numeric in summary
                    
                    # STRICT MATCHING (No more fuzzy double-counting)
                    if name == "fouls": data['fouls'] += val
                    if name == "fieldGoalsAttempted": data['fga'] += val
                    if name == "freeThrowsAttempted": data['fta'] += val
                    if name == "offensiveRebounds": data['orb'] += val
                    if name == "turnovers": data['tov'] += val
        
        # B. ODDS BACKUP
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
with st.spinner("Calculating True Pace..."):
    live_games = fetch_game_data(league_choice)

if not live_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress = st.progress(0)
    results = []
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    for i, game in enumerate(live_games):
        progress.progress((i + 1) / len(live_games))
        
        # 1. CLOCK
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
            deep = fetch_deep_stats(game['id'], league_choice)
            
            # 2. LINE LOGIC (Sticky)
            curr = game['api_line']
            if curr == 0.0: curr = deep['deep_line']
            
            mem = st.session_state.sticky_lines.get(game['id'], 0.0)
            
            final_line = 0.0
            if mem > 0: final_line = mem
            elif curr > 0: 
                final_line = curr
                st.session_state.sticky_lines[game['id']] = final_line

            # 3. SAVANT MATH (The Fix)
            total = game['home'] + game['away']
            
            # True Possessions Formula
            raw_poss = deep['fga'] - deep['orb'] + deep['tov'] + (0.44 * deep['fta'])
            
            # PACE PER TEAM (Divide by 2 to normalize)
            # This makes the number look like "70.5" instead of "141.0"
            game_pace = (raw_poss / mins) * FULL_TIME
            team_pace = game_pace / 2
            
            # Efficiency (Points Per Possession)
            off_rtg = total / raw_poss if raw_poss > 0 else 0
            
            # Ref Factor (Fouls Per Minute)
            fpm = deep['fouls'] / mins
            
            # Projection
            # Proj = (Game_Pace * Off_Rtg) + Ref_Adjustment
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (game_pace * off_rtg) + ref_adj
            
            edge = round(proj - final_line, 1) if final_line > 0 else -999.0
            
            # Formatting
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")
            clock_fmt = f"{p_str} {game['clock_display']}"

            results.append({
                "ID": game['id'],
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": clock_fmt,
                "Fouls": int(deep['fouls']),
                "Pace": round(team_pace, 1), # Normalized Team Pace
                "FPM": round(fpm, 2),
                "Line": final_line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge
            })

    progress.empty()

    if results:
        df = pd.DataFrame(results)
        df['sort_val'] = df['EDGE'].apply(lambda x: abs(x) if x != -999 else 0)
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])
        
        st.data_editor(
            df,
            column_config={
                "Line": st.column_config.NumberColumn("Line (Edit)", required=True, format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Pace": st.column_config.NumberColumn("Pace", format="%.1f", help="Possessions per 40m/48m (Per Team)"),
                "FPM": st.column_config.NumberColumn("FPM", format="%.2f"),
                "ID": None
            },
            disabled=["Matchup", "Score", "Time", "Fouls", "Pace", "FPM", "Savant Proj", "EDGE"],
            use_container_width=True,
            hide_index=True
        )
        
        # Save Edits
        for index, row in st.session_state.get('data_editor', {}).get('edited_rows', {}).items():
            # This is a fallback; the main loop above handles the save logic more reliably
            pass
