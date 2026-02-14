import streamlit as st
import pandas as pd
import requests
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v34: Fail-Safe", layout="wide")
st.title("🏀 Savant v34: The Safety Net")

# --- MEMORY ---
if 'sticky_lines' not in st.session_state:
    st.session_state.sticky_lines = {} 

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    use_regression = st.toggle("Regression Mode", value=True)
    
    if st.button("🔄 REFRESH DATA", type="primary"):
        st.rerun()

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

# --- STEP 2: DEEP STATS (THE FAIL-SAFE) ---
def fetch_deep_stats(game_id, league, home_score, away_score):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    
    data = {"fouls":0, "fga":0, "fta":0, "orb":0, "tov":0, "deep_line": 0.0, "ftm": 0}
    
    try:
        res = requests.get(url, timeout=4).json()
        
        # A. PARSE BOX SCORE
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                stats_map = {}
                # Map name -> raw value
                for stat in team.get('statistics', []):
                    stats_map[stat.get('name', '')] = stat.get('displayValue', '0')
                
                # 1. FIELD GOALS (The Cascade)
                fga_val = 0.0
                if 'fieldGoalsAttempted' in stats_map:
                    fga_val = float(stats_map['fieldGoalsAttempted'])
                elif 'fieldGoals' in stats_map:
                    raw = stats_map['fieldGoals']
                    if "-" in raw: fga_val = float(raw.split('-')[1])
                data['fga'] += fga_val

                # 2. FREE THROWS
                fta_val = 0.0
                ftm_val = 0.0
                if 'freeThrowsAttempted' in stats_map:
                    fta_val = float(stats_map['freeThrowsAttempted'])
                    # If we have FTM separate, grab it
                    if 'freeThrowsMade' in stats_map:
                        ftm_val = float(stats_map['freeThrowsMade'])
                elif 'freeThrows' in stats_map:
                    raw = stats_map['freeThrows']
                    if "-" in raw: 
                        parts = raw.split('-')
                        ftm_val = float(parts[0])
                        fta_val = float(parts[1])
                
                data['fta'] += fta_val
                data['ftm'] += ftm_val
                
                # 3. OTHER STATS
                if 'offensiveRebounds' in stats_map:
                    data['orb'] += float(stats_map['offensiveRebounds'])
                if 'turnovers' in stats_map:
                    data['tov'] += float(stats_map['turnovers'])
                if 'fouls' in stats_map:
                    data['fouls'] += float(stats_map['fouls'])

        # B. THE FAIL-SAFE (Plan C)
        # If FGA is STILL 0 after all that parsing, we estimate it from points.
        # Logic: (Total Points - Free Throws Made) / 2 = Approx FGA
        if data['fga'] == 0:
            total_points = home_score + away_score
            approx_fga = (total_points - data['ftm']) / 2
            data['fga'] = approx_fga

        # C. ODDS BACKUP
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
with st.spinner("Calculating..."):
    live_games = fetch_game_data(league_choice)

if not live_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress = st.progress(0)
    results = []
    
    if league_choice == "NBA":
        FULL_TIME = 48.0
        AVG_EFF = 1.12
    else:
        FULL_TIME = 40.0
        AVG_EFF = 1.04 
    
    for i, game in enumerate(live_games):
        progress.progress((i + 1) / len(live_games))
        
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
            # Pass score to deep_stats for fail-safe calculation
            deep = fetch_deep_stats(game['id'], league_choice, game['home'], game['away'])
            
            # Line Logic
            curr = game['api_line']
            if curr == 0.0: curr = deep['deep_line']
            mem = st.session_state.sticky_lines.get(game['id'], 0.0)
            
            final_line = 0.0
            if mem > 0: final_line = mem
            elif curr > 0: 
                final_line = curr
                st.session_state.sticky_lines[game['id']] = final_line

            # MATH
            total = game['home'] + game['away']
            
            # Possessions
            raw_poss = deep['fga'] - deep['orb'] + deep['tov'] + (0.44 * deep['fta'])
            
            # Safeguard: Prevent division by zero if stats are totally dead
            if raw_poss <= 0: raw_poss = 1.0 
            
            proj_pace = (raw_poss / mins) * FULL_TIME
            current_eff = total / raw_poss
            
            # Regression
            if use_regression:
                weight = min(mins / FULL_TIME, 1.0)
                final_eff = (current_eff * weight) + (AVG_EFF * (1 - weight))
            else:
                final_eff = current_eff
            
            fpm = deep['fouls'] / mins
            ref_adj = (fpm - 1.2) * 8.0 if fpm > 1.2 else 0 
            
            proj = (proj_pace * final_eff) + ref_adj
            
            edge = round(proj - final_line, 1) if final_line > 0 else -999.0
            
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")

            results.append({
                "ID": game['id'],
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": f"{p_str} {game['clock_display']}",
                "Fouls": int(deep['fouls']),
                "Pace": round(proj_pace / 2, 1), 
                "PPP": round(current_eff, 2), 
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
                "Pace": st.column_config.NumberColumn("Pace", format="%.1f"),
                "PPP": st.column_config.NumberColumn("PPP", format="%.2f"),
                "ID": None
            },
            disabled=["Matchup", "Score", "Time", "Fouls", "Pace", "PPP", "Savant Proj", "EDGE"],
            use_container_width=True,
            hide_index=True
        )
        
        for index, row in st.session_state.get('data_editor', {}).get('edited_rows', {}).items():
            pass
