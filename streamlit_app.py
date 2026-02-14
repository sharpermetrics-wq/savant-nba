import streamlit as st
import pandas as pd
import requests
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v24: Auto-Lock", layout="wide")
st.title("🏀 Savant v24: The Auto-Lock Engine")

# --- SESSION STATE (For Backup Memory) ---
if 'lines_memory' not in st.session_state:
    st.session_state.lines_memory = {}

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    # BIG REFRESH BUTTON
    if st.button("🚀 FORCE REFRESH (LINES + STATS)", type="primary"):
        st.rerun()

# --- STEP 1: GET LIVE GAMES ---
def get_live_games(league):
    ts = int(time.time()) # Cache Buster
    if league == "NBA":
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100&t={ts}"
        fd_url = "https://sportsbook.fanduel.com/navigation/nba"
    else:
        # groups=50 unlocks ALL Division I
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000&t={ts}"
        fd_url = "https://sportsbook.fanduel.com/navigation/ncaab"
    
    try:
        headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
        res = requests.get(url, headers=headers, timeout=8).json()
        games = []
        for event in res.get('events', []):
            if event['status']['type']['state'] == 'in':
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_display": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home": int(event['competitions'][0]['competitors'][0]['score']),
                    "away": int(event['competitions'][0]['competitors'][1]['score']),
                    "fd_link": fd_url
                })
        return games
    except: return []

# --- STEP 2: GET DEEP STATS & HUNT ODDS (THE BLOODHOUND IS BACK) ---
def get_game_data(game_id, league):
    ts = int(time.time())
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    # We hit the SUMMARY endpoint because it has PickCenter (Odds) AND BoxScore (Stats)
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}&t={ts}"
    
    data = {
        "fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0, 
        "line": 0.0, "book": "---"
    }
    
    try:
        res = requests.get(url, timeout=6).json()
        
        # A. PARSE STATS (Fouls/Pace)
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

        # B. ODDS BLOODHOUND (The Aggressive Search)
        # We look for ANY provider that has a line > 100
        found_line = False
        
        if 'pickcenter' in res:
            # Priority 1: FanDuel
            for p in res['pickcenter']:
                if 'fanduel' in p.get('provider', {}).get('name', '').lower() and 'overUnder' in p:
                    try:
                        val = float(p['overUnder'])
                        if val > 100:
                            data['line'] = val
                            data['book'] = "FanDuel"
                            found_line = True
                            break
                    except: continue
            
            # Priority 2: DraftKings
            if not found_line:
                for p in res['pickcenter']:
                    if 'draftkings' in p.get('provider', {}).get('name', '').lower() and 'overUnder' in p:
                        try:
                            val = float(p['overUnder'])
                            if val > 100:
                                data['line'] = val
                                data['book'] = "DraftKings"
                                found_line = True
                                break
                        except: continue
            
            # Priority 3: Anyone else
            if not found_line:
                for p in res['pickcenter']:
                    if 'overUnder' in p:
                        try:
                            val = float(p['overUnder'])
                            if val > 100:
                                data['line'] = val
                                data['book'] = p.get('provider', {}).get('name', 'Book')
                                found_line = True
                                break
                        except: continue

        return data
    except: return data

# --- STEP 3: THE ENGINE ---
with st.spinner("Hunting Lines & Stats..."):
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
            if ":" in game['clock_display']: m, s = map(int, game['clock_display'].split(':'))
            else: m, s = 0, 0
            
            p = game['period']
            mins = 0.0
            
            if league_choice == "NBA":
                if p <= 4: mins = ((p-1)*12) + (12 - m - (s/60))
                else: mins = 48.0 + ((p-4)*5) - m - (s/60)
            else: # College
                if p == 1: mins = 20.0 - m - (s/60)
                elif p == 2: mins = 20.0 + (20.0 - m - (s/60))
                else: mins = 40.0 + ((p-2)*5) - m - (s/60)
        except: mins = 0.0

        if mins > 2.0:
            # FETCH DEEP DATA
            game_data = get_game_data(game['id'], league_choice)
            
            # --- INTELLIGENT LINE MERGE ---
            # 1. API Line is King
            final_line = game_data['line']
            book_name = game_data['book']
            
            # 2. If API is 0, check Memory
            if final_line == 0.0:
                final_line = st.session_state.lines_memory.get(game['id'], 0.0)
                if final_line > 0.0:
                    book_name = "Saved"
            else:
                # 3. If API is good, update Memory for next time
                st.session_state.lines_memory[game['id']] = final_line

            # SAVANT MATH
            total = game['home'] + game['away']
            fpm = game_data['fouls'] / mins
            poss = game_data['fga'] - game_data['orb'] + game_data['tov'] + (0.44 * game_data['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            edge = round(proj - final_line, 1) if final_line > 0 else -999.0
            
            # Clock Formatting
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")
            clean_clock = f"{p_str} {game['clock_display']}"

            results.append({
                "ID": game['id'], # Hidden
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": clean_clock,
                "Book": book_name,
                "Fouls": int(game_data['fouls']),
                "Pace": round(pace * FULL_TIME, 1),
                "FPM": round(fpm, 2),
                "Line": final_line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge,
                "Link": game['fd_link']
            })
            
    progress_bar.empty()

    if results:
        df = pd.DataFrame(results)
        
        # Sort by Absolute Edge
        df['sort_val'] = df['EDGE'].apply(lambda x: abs(x) if x != -999 else 0)
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])
        
        # --- DISPLAY ---
        edited_df = st.data_editor(
            df,
            column_config={
                "Link": st.column_config.LinkColumn("Bet", display_text="FanDuel 📲"),
                "Line": st.column_config.NumberColumn("Line", required=True, format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Book": st.column_config.TextColumn("Book", disabled=True),
                "ID": None
            },
            disabled=["Matchup", "Score", "Time", "Book", "Fouls", "Pace", "FPM", "Savant Proj", "EDGE", "Link"],
            use_container_width=True,
            hide_index=True
        )
        
        # Capture manual edits back to memory (just in case)
        for index, row in edited_df.iterrows():
            if row['Line'] > 0:
                st.session_state.lines_memory[row['ID']] = row['Line']
