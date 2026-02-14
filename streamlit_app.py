import streamlit as st
import pandas as pd
import requests
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v23: Persistent", layout="wide")
st.title("🏀 Savant v23: Persistent State Engine")

# --- SESSION STATE SETUP ---
if 'game_data' not in st.session_state:
    st.session_state.game_data = {}

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🔄 REFRESH SCORES & CLOCKS", type="primary"):
        st.rerun()
    
    st.divider()
    st.caption("ℹ️ Edits to 'Line' are now saved between refreshes.")

# --- STEP 1: GET LIVE DATA ---
def get_espn_data(league):
    ts = int(time.time())
    if league == "NBA":
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100&t={ts}"
        fd_url = "https://sportsbook.fanduel.com/navigation/nba"
    else:
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000&t={ts}"
        fd_url = "https://sportsbook.fanduel.com/navigation/ncaab"
    
    try:
        headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
        res = requests.get(url, headers=headers, timeout=8).json()
        games = []
        
        for event in res.get('events', []):
            if event['status']['type']['state'] == 'in':
                comp = event['competitions'][0]
                
                # Odds Logic (Scoreboard Source)
                line = 0.0
                book = "---"
                if 'odds' in comp:
                    for odd in comp['odds']:
                        if 'overUnder' in odd:
                            try:
                                val = float(odd['overUnder'])
                                if val > 100:
                                    line = val
                                    book = odd.get('provider', {}).get('name', 'ESPN')
                                    break
                            except: continue
                
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_raw": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home": int(comp['competitors'][0]['score']),
                    "away": int(comp['competitors'][1]['score']),
                    "api_line": line, # Raw API line
                    "book": book,
                    "fd_link": fd_url
                })
        return games
    except: return []

# --- STEP 2: GET DEEP STATS ---
def get_deep_stats(game_id, league):
    ts = int(time.time())
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}&t={ts}"
    
    data = {"fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0}
    try:
        res = requests.get(url, timeout=4).json()
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
        return data
    except: return data

# --- STEP 3: THE MERGE ENGINE ---
with st.spinner("Syncing Live Data..."):
    active_games = get_espn_data(league_choice)

if not active_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress_bar = st.progress(0)
    results = []
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    for i, game in enumerate(active_games):
        progress_bar.progress((i + 1) / len(active_games))
        
        # 1. Clock Math
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
            stats = get_deep_stats(game['id'], league_choice)
            
            total = game['home'] + game['away']
            fpm = stats['fouls'] / mins
            poss = stats['fga'] - stats['orb'] + stats['tov'] + (0.44 * stats['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            # --- PERSISTENCE LOGIC ---
            # Check if we have a saved manual line for this game ID
            saved_line = st.session_state.game_data.get(game['id'], 0.0)
            
            # If the API sends a 0, but we have a saved line, use the saved one.
            # If the API sends a valid line, update the save.
            final_line = game['api_line']
            if final_line == 0.0 and saved_line > 0.0:
                final_line = saved_line
            
            # Save it back to session state
            st.session_state.game_data[game['id']] = final_line
            
            edge = round(proj - final_line, 1) if final_line > 0 else -999.0
            
            # Clock Display
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")
            clean_clock = f"{p_str} {game['clock_raw']}"

            results.append({
                "ID": game['id'], # Hidden ID for tracking
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": clean_clock,
                "Fouls": int(stats['fouls']),     # BACK IN
                "Pace": round(pace * FULL_TIME, 1), # BACK IN
                "FPM": round(fpm, 2),             # BACK IN
                "Line": final_line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge,
                "Link": game['fd_link']
            })
            
    progress_bar.empty()

    if results:
        df = pd.DataFrame(results)
        
        # Sort
        df['sort_val'] = df['EDGE'].apply(lambda x: abs(x) if x != -999 else 0)
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])
        
        # EDITABLE DISPLAY
        edited_df = st.data_editor(
            df,
            column_config={
                "Link": st.column_config.LinkColumn("Bet", display_text="FanDuel 📲"),
                "Line": st.column_config.NumberColumn("Line (Edit)", required=True, format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Fouls": st.column_config.NumberColumn("Fouls", format="%d"),
                "Pace": st.column_config.NumberColumn("Pace", format="%.1f"),
                "FPM": st.column_config.NumberColumn("FPM", format="%.2f"),
                "ID": None # Hide ID column
            },
            disabled=["Matchup", "Score", "Time", "Fouls", "Pace", "FPM", "Savant Proj", "EDGE", "Link"],
            use_container_width=True,
            hide_index=True,
            key="main_editor"
        )
        
        # --- UPDATE SESSION STATE FROM EDITS ---
        # This captures your edits instantly so they survive the NEXT refresh
        for index, row in edited_df.iterrows():
            g_id = row['ID']
            new_line = row['Line']
            # If the user changed the line in the editor, update the persistence dict
            if new_line != st.session_state.game_data.get(g_id):
                st.session_state.game_data[g_id] = new_line
