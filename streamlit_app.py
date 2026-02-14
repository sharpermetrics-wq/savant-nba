import streamlit as st
import pandas as pd
import requests
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v25: Kitchen Sink", layout="wide")
st.title("🏀 Savant v25: Total Retrieval Protocol")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🚀 FORCE RETRIEVAL", type="primary"):
        st.rerun()

# --- HELPER: REGEX PARSER ---
def extract_total(text):
    # Aggressively looks for any number following "O/U" or just a large float like 145.5
    try:
        # Case 1: "O/U 145.5"
        match = re.search(r'O/U\s*(\d{3}\.?\d*)', str(text), re.IGNORECASE)
        if match: return float(match.group(1))
        return 0.0
    except: return 0.0

# --- STEP 1: GET LIVE GAMES & SCOREBOARD ODDS ---
def get_live_games(league):
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
                
                # --- LAYER 1: SCOREBOARD ODDS ---
                sb_line = 0.0
                
                # Check 1: The 'details' text string (Most reliable for totals)
                if 'odds' in comp:
                    for odd in comp['odds']:
                        if 'details' in odd:
                            val = extract_total(odd['details'])
                            if val > 100: 
                                sb_line = val
                                break
                        # Check 2: The 'overUnder' number
                        if sb_line == 0.0 and 'overUnder' in odd:
                            try:
                                val = float(odd['overUnder'])
                                if val > 100: sb_line = val
                            except: pass
                
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_raw": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home": int(comp['competitors'][0]['score']),
                    "away": int(comp['competitors'][1]['score']),
                    "sb_line": sb_line  # Pass this down
                })
        return games
    except: return []

# --- STEP 2: DEEP STATS & DEEP ODDS ---
def get_deep_data(game_id, league):
    ts = int(time.time())
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}&t={ts}"
    
    data = {"fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0, "deep_line": 0.0}
    
    try:
        res = requests.get(url, timeout=5).json()
        
        # A. STATS
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                for stat in team.get('statistics', []):
                    val = 0.0
                    try:
                        raw = stat.get('displayValue', '0')
                        val = float(raw.split('-')[1]) if "-" in raw else float(raw)
                    except: val = 0.0
                    
                    nm = stat.get('name', '').lower()
                    lbl = stat.get('label', '').lower()
                    
                    if "foul" in nm or "pf" in lbl: data['fouls'] += val
                    if "field" in nm or "fg" in lbl: data['fga'] += val
                    if "free" in nm or "ft" in lbl: data['fta'] += val
                    if "offensive" in nm or "orb" in lbl: data['orb'] += val
                    if "turnover" in nm or "to" in lbl: data['tov'] += val

        # B. ODDS (LAYER 3 & 4)
        # Only look if we didn't find it in the scoreboard (optimized later)
        # Check PickCenter
        if 'pickcenter' in res:
            for p in res['pickcenter']:
                if 'overUnder' in p:
                    try:
                        val = float(p['overUnder'])
                        if val > 100:
                            data['deep_line'] = val
                            break # Found one, stop looking
                    except: continue
        
        return data
    except: return data

# --- STEP 3: EXECUTION ---
with st.spinner("Executing Kitchen Sink Protocol..."):
    active_games = get_live_games(league_choice)

if not active_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress_bar = st.progress(0)
    results = []
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    for i, game in enumerate(active_games):
        progress_bar.progress((i + 1) / len(active_games))
        
        # Clock Logic
        try:
            if ":" in game['clock_raw']: m, s = map(int, game['clock_raw'].split(':'))
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
            deep_data = get_deep_data(game['id'], league_choice)
            
            # --- THE ODDS MERGE ---
            # Use Scoreboard Line first (Layer 1/2), if missing use Deep Line (Layer 3/4)
            final_line = game['sb_line']
            if final_line == 0.0:
                final_line = deep_data['deep_line']
            
            # MATH
            total = game['home'] + game['away']
            fpm = deep_data['fouls'] / mins
            poss = deep_data['fga'] - deep_data['orb'] + deep_data['tov'] + (0.44 * deep_data['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            edge = round(proj - final_line, 1) if final_line > 0 else -999.0
            
            # Formatting
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")
            clean_clock = f"{p_str} {game['clock_raw']}"
            fd_link = "https://sportsbook.fanduel.com/navigation/ncaab" if league_choice != "NBA" else "https://sportsbook.fanduel.com/navigation/nba"

            results.append({
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": clean_clock,
                "Fouls": int(deep_data['fouls']),
                "Pace": round(pace * FULL_TIME, 1),
                "FPM": round(fpm, 2),
                "Line": final_line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge,
                "Link": fd_link
            })
            
    progress_bar.empty()

    if results:
        df = pd.DataFrame(results)
        
        # Sort
        df['sort_val'] = df['EDGE'].apply(lambda x: abs(x) if x != -999 else 0)
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])
        
        # DISPLAY
        st.data_editor(
            df,
            column_config={
                "Link": st.column_config.LinkColumn("Bet", display_text="FanDuel 📲"),
                "Line": st.column_config.NumberColumn("Line (Edit)", required=True, format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Fouls": st.column_config.NumberColumn("Fouls", format="%d"),
                "Pace": st.column_config.NumberColumn("Pace", format="%.1f"),
                "FPM": st.column_config.NumberColumn("FPM", format="%.2f"),
            },
            disabled=["Matchup", "Score", "Time", "Fouls", "Pace", "FPM", "Savant Proj", "EDGE", "Link"],
            use_container_width=True,
            hide_index=True
        )
