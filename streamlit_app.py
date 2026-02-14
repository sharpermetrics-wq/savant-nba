import streamlit as st
import pandas as pd
import requests
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v35: Decoupled", layout="wide")
st.title("🏀 Savant v35: The Decoupled Engine")

# --- MEMORY ---
if 'sticky_lines' not in st.session_state:
    st.session_state.sticky_lines = {} 

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🔄 REFRESH DATA", type="primary"):
        st.rerun()
    
    st.info("ℹ️ Projection is now based on Scoring Pace + Ref Adjustment (Robust to bad data).")

# --- HELPER ---
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

# --- STEP 2: DEEP STATS ---
def fetch_deep_stats(game_id, league):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    
    data = {"fouls":0, "fga":0, "fta":0, "orb":0, "tov":0, "deep_line": 0.0}
    try:
        res = requests.get(url, timeout=4).json()
        
        # A. PARSE BOX SCORE
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                for stat in team.get('statistics', []):
                    # Universal Matcher
                    nm = stat.get('name', '').lower()
                    lbl = stat.get('label', '').lower()
                    val = 0.0
                    try:
                        raw = stat.get('displayValue', '0')
                        if "-" in raw: val = float(raw.split('-')[1])
                        else: val = float(raw)
                    except: val = 0.0
                    
                    if "foul" in nm or "pf" in lbl: data['fouls'] += val
                    if "offensive" in nm or "orb" in lbl: data['orb'] += val
                    if "turnover" in nm or "to" in lbl: data['tov'] += val
                    if ("field" in nm or "fg" in lbl) and not ("three" in nm or "3pt" in lbl):
                        data['fga'] += val
                    if "free" in nm or "ft" in lbl: data['fta'] += val
        
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
with st.spinner("Decoupling Metrics..."):
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
            
            # Line Logic
            curr = game['api_line']
            if curr == 0.0: curr = deep['deep_line']
            mem = st.session_state.sticky_lines.get(game['id'], 0.0)
            final_line = mem if mem > 0 else curr
            if final_line > 0: st.session_state.sticky_lines[game['id']] = final_line

            # --- SAVANT V35 MATH (The Robust Method) ---
            total_score = game['home'] + game['away']
            
            # 1. Base Projection (Linear Scoring Pace)
            # This is "Points Per Minute * Full Time"
            # It relies ONLY on Score and Time (100% reliable)
            base_proj = (total_score / mins) * FULL_TIME
            
            # 2. Ref Adjustment (The Savant Boost)
            # We add points if fouls are high
            fpm = deep['fouls'] / mins
            ref_adj = (fpm - 1.2) * 8.0 if fpm > 1.2 else 0 
            
            # 3. Final Proj
            proj = base_proj + ref_adj
            
            # 4. Display Metrics (Decoupled from Projection)
            # These are for your eyes only, they don't break the proj if they are wrong
            raw_poss = deep['fga'] - deep['orb'] + deep['tov'] + (0.44 * deep['fta'])
            display_pace = (raw_poss / mins) * FULL_TIME if raw_poss > 0 else 0
            
            edge = round(proj - final_line, 1) if final_line > 0 else -999.0
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")

            results.append({
                "ID": game['id'],
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": f"{p_str} {game['clock_display']}",
                "Line": final_line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge,
                "Fouls": int(deep['fouls']),
                "FPM": round(fpm, 2),
                "Pace": round(display_pace / 2, 1) # Display Team Pace
            })

    progress.empty()

    if results:
        df = pd.DataFrame(results)
        df['sort_val'] = df['EDGE'].apply(lambda x: abs(x) if x != -999 else 0)
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])
        
        edited_df = st.data_editor(
            df,
            column_config={
                "Line": st.column_config.NumberColumn("Line (Edit)", required=True, format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Pace": st.column_config.NumberColumn("Pace", format="%.1f"),
                "FPM": st.column_config.NumberColumn("FPM", format="%.2f"),
                "ID": None
            },
            disabled=["Matchup", "Score", "Time", "Fouls", "Pace", "FPM", "Savant Proj", "EDGE"],
            use_container_width=True,
            hide_index=True
        )
        
        # Save Edits
        for index, row in edited_df.iterrows():
            if row['Line'] > 0 and row['Line'] != st.session_state.sticky_lines.get(row['ID']):
                st.session_state.sticky_lines[row['ID']] = row['Line']
