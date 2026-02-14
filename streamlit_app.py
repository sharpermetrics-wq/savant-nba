import streamlit as st
import pandas as pd
import requests
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v20: Bookie Hunter", layout="wide")
st.title("🏀 Savant v20: The Bookie Hunter")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    # BIG REFRESH BUTTON
    if st.button("🔄 REFRESH LINES & SCORES", type="primary"):
        st.rerun()
    
    st.divider()
    st.caption("ℹ️ Priority: FanDuel > DraftKings > ESPN BET > Others")

# --- HELPER: TEXT PARSER ---
def parse_ou(text):
    try:
        match = re.search(r'(\d{3}\.?\d*)', str(text))
        if match: return float(match.group(1))
        return 0.0
    except: return 0.0

# --- STEP 1: GET ACTIVE GAMES ---
def get_live_games(league):
    if league == "NBA":
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100"
        fd_url = "https://sportsbook.fanduel.com/navigation/nba"
    else:
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000"
        fd_url = "https://sportsbook.fanduel.com/navigation/ncaab"
    
    try:
        res = requests.get(url, timeout=10).json()
        games = []
        for event in res.get('events', []):
            if event['status']['type']['state'] == 'in':
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_raw": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home": int(event['competitions'][0]['competitors'][0]['score']),
                    "away": int(event['competitions'][0]['competitors'][1]['score']),
                    "fd_link": fd_url
                })
        return games
    except: return []

# --- STEP 2: GET DEEP DATA & BOOKIE HUNT ---
def get_game_data(game_id, league):
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}"
    
    data = {
        "fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0, 
        "line": 0.0, "book": "---"
    }
    
    try:
        res = requests.get(url, timeout=6).json()
        
        # A. PARSE STATS
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
                    
                    if "foul" in nm or "pf" in lbl: data['fouls'] += val
                    if "field" in nm or "fg" in lbl: data['fga'] += val
                    if "free" in nm or "ft" in lbl: data['fta'] += val
                    if "offensive" in nm or "orb" in lbl: data['orb'] += val
                    if "turnover" in nm or "to" in lbl: data['tov'] += val

        # B. BOOKIE HUNTING (Priority Logic)
        found_fd = False
        found_dk = False
        
        if 'pickcenter' in res:
            # Pass 1: Look for FanDuel specifically
            for provider in res['pickcenter']:
                name = provider.get('provider', {}).get('name', '').lower()
                if 'fanduel' in name and 'overUnder' in provider:
                    try:
                        val = float(provider['overUnder'])
                        if val > 100:
                            data['line'] = val
                            data['book'] = "FanDuel"
                            found_fd = True
                            break
                    except: continue
            
            # Pass 2: Look for DraftKings if no FanDuel
            if not found_fd:
                for provider in res['pickcenter']:
                    name = provider.get('provider', {}).get('name', '').lower()
                    if 'draftkings' in name and 'overUnder' in provider:
                        try:
                            val = float(provider['overUnder'])
                            if val > 100:
                                data['line'] = val
                                data['book'] = "DraftKings"
                                found_dk = True
                                break
                        except: continue

            # Pass 3: Take ANYTHING if neither found
            if not found_fd and not found_dk:
                for provider in res['pickcenter']:
                    if 'overUnder' in provider:
                        try:
                            val = float(provider['overUnder'])
                            if val > 100:
                                data['line'] = val
                                # Shorten "Caesars Sportsbook" to "Caesars"
                                raw_name = provider.get('provider', {}).get('name', 'Gen')
                                data['book'] = raw_name.replace(" Sportsbook", "").replace("ESPN BET", "ESPN")
                                break
                        except: continue
        
        return data
    except: return data

# --- STEP 3: EXECUTION ---
with st.spinner("Hunting Odds (Priority: FanDuel > DK)..."):
    active_games = get_live_games(league_choice)

if not active_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress_bar = st.progress(0)
    results = []
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    for i, game in enumerate(active_games):
        progress_bar.progress((i + 1) / len(active_games))
        
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
            game_data = get_game_data(game['id'], league_choice)
            
            total = game['home'] + game['away']
            fpm = game_data['fouls'] / mins
            poss = game_data['fga'] - game_data['orb'] + game_data['tov'] + (0.44 * game_data['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            line = game_data['line']
            edge = round(proj - line, 1) if line > 0 else -999.0

            results.append({
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": f"{round(mins,1)}",
                "Book": game_data['book'],  # NEW COLUMN
                "Line": line,
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
        
        st.data_editor(
            df,
            column_config={
                "Link": st.column_config.LinkColumn("Bet", display_text="FanDuel 📲"),
                "Line": st.column_config.NumberColumn("Line (Edit)", required=True, format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Book": st.column_config.TextColumn("Bookie", disabled=True)
            },
            disabled=["Matchup", "Score", "Time", "Book", "Savant Proj", "EDGE", "Link"],
            use_container_width=True,
            hide_index=True
        )
