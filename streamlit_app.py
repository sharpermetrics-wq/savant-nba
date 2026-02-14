import streamlit as st
import pandas as pd
import requests
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v18: Odds Hunter", layout="wide")
st.title("🏀 Savant v18: The 'Odds Hunter'")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🚀 FORCE REFRESH", type="primary"):
        st.rerun()
    
    st.info("ℹ️ Tip: If a line shows '0.0', double-click the cell in the table to type it in manually.")

# --- HELPER: TEXT PARSER ---
def extract_ou_from_text(text):
    # Looks for pattern "O/U 145.5" or "145.5 O/U"
    try:
        match = re.search(r'O/U\s*(\d+\.?\d*)', text, re.IGNORECASE)
        if match: return float(match.group(1))
        return 0.0
    except: return 0.0

# --- STEP 1: GET GAMES & ODDS (AGGRESSIVE) ---
def get_live_games(league):
    if league == "NBA":
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100"
        fd_url = "https://sportsbook.fanduel.com/navigation/nba"
    else:
        # groups=50 unlocks ALL Division I
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000"
        fd_url = "https://sportsbook.fanduel.com/navigation/ncaab"
    
    try:
        res = requests.get(url, timeout=10).json()
        games = []
        
        for event in res.get('events', []):
            comp = event['competitions'][0]
            status = event['status']['type']['state']
            
            if status == 'in':
                # --- THE FIX: AGGRESSIVE ODDS HUNTING ---
                line = 0.0
                
                # Method A: dedicated 'overUnder' float
                if 'odds' in comp:
                    for odd in comp['odds']:
                        if odd.get('overUnder'):
                            line = float(odd['overUnder'])
                            break
                        # Method B: Parse 'details' string (e.g. "UK -5.0, O/U 155.5")
                        if 'details' in odd:
                            val = extract_ou_from_text(odd['details'])
                            if val > 0: 
                                line = val
                                break

                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_raw": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home_score": int(comp['competitors'][0]['score']),
                    "away_score": int(comp['competitors'][1]['score']),
                    "line": line, # Might be 0.0 if totally missing
                    "fd_link": fd_url
                })
        return games
    except: return []

# --- STEP 2: GET BOX SCORE ---
def get_box_stats(game_id, league):
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}"
    
    stats = {"fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0}
    try:
        res = requests.get(url, timeout=5).json()
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                for stat in team.get('statistics', []):
                    val = 0.0
                    try:
                        raw = stat.get('displayValue', '0')
                        val = float(raw.split('-')[1]) if "-" in raw else float(raw)
                    except: val = 0.0
                    
                    lbl = stat.get('label', '').lower()
                    nm = stat.get('name', '').lower()
                    
                    if "foul" in nm or "pf" in lbl: stats['fouls'] += val
                    if "field" in nm or "fg" in lbl: stats['fga'] += val
                    if "free" in nm or "ft" in lbl: stats['fta'] += val
                    if "offensive" in nm or "orb" in lbl: stats['orb'] += val
                    if "turnover" in nm or "to" in lbl: stats['tov'] += val
        return stats
    except: return stats

# --- STEP 3: THE ENGINE ---
with st.spinner("Hunting Odds..."):
    active_games = get_live_games(league_choice)

if not active_games:
    st.info(f"No active {league_choice} games found.")
else:
    # Progress Bar
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
            else: # College
                if p == 1: mins = 20.0 - m - (s/60)
                elif p == 2: mins = 20.0 + (20.0 - m - (s/60))
                else: mins = 40.0 + ((p-2)*5) - m - (s/60)
        except: mins = 0.0

        if mins > 2.0:
            box = get_box_stats(game['id'], league_choice)
            
            total = game['home_score'] + game['away_score']
            fpm = box['fouls'] / mins
            poss = box['fga'] - box['orb'] + box['tov'] + (0.44 * box['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            # We calculate edge later in the display loop to handle manual edits
            results.append({
                "Matchup": game['matchup'],
                "Score": f"{game['away_score']}-{game['home_score']}",
                "Time": f"{round(mins,1)}",
                "FPM": round(fpm, 2),
                "Savant Proj": round(proj, 1),
                "Line": game['line'], # KEEP AS FLOAT FOR EDITING
                "Link": game['fd_link']
            })
            
    progress_bar.empty()

    if results:
        df = pd.DataFrame(results)
        
        st.markdown("### 📊 Live Board (Double-click 'Line' to edit)")
        
        # --- EDITABLE TABLE ---
        # This allows you to fix the "0.0" lines yourself
        edited_df = st.data_editor(
            df,
            column_config={
                "Link": st.column_config.LinkColumn("Bet", display_text="FanDuel 📲"),
                "Line": st.column_config.NumberColumn("Line (Edit Me)", required=True),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "FPM": st.column_config.NumberColumn("
