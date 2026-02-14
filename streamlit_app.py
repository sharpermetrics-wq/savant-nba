import streamlit as st
import pandas as pd
import requests
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v33: Deduplicated", layout="wide")
st.title("🏀 Savant v33: The Stability Fix")

# --- MEMORY ---
if 'sticky_lines' not in st.session_state:
    st.session_state.sticky_lines = {} 

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    # REGRESSION TOGGLE
    use_regression = st.toggle("Regression Mode", value=True, 
        help="Blends current shooting % with league average to prevent early game outliers.")
    
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

# --- STEP 2: DEEP STATS (THE DEDUPLICATOR) ---
def fetch_deep_stats(game_id, league):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    
    # We aggregate stats for the whole game here
    game_stats = {"fouls":0, "fga":0, "fta":0, "orb":0, "tov":0, "deep_line": 0.0}
    
    try:
        res = requests.get(url, timeout=4).json()
        
        # A. PARSE BOX SCORE (Strict Team Loop)
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                
                # Temp dict for THIS team to avoid double counting across categories
                t_stats = {"fga": 0, "fta": 0, "orb": 0, "tov": 0, "fouls": 0}
                
                # We convert the list of stats into a dictionary keyed by 'name' for instant lookup
                # This is the secret sauce: We map "name": "value" so we can pick exactly what we want.
                stats_map = {}
                for stat in team.get('statistics', []):
                    name = stat.get('name', '')
                    raw = stat.get('displayValue', '0')
                    stats_map[name] = raw
                
                # 1. FIELD GOALS (Strict Priority)
                if 'fieldGoalsAttempted' in stats_map:
                    t_stats['fga'] = float(stats_map['fieldGoalsAttempted'])
                elif 'fieldGoals' in stats_map:
                    # Parse "20-55"
                    raw = stats_map['fieldGoals']
                    if "-" in raw: t_stats['fga'] = float(raw.split('-')[1])

                # 2. FREE THROWS
                if 'freeThrowsAttempted' in stats_map:
                    t_stats['fta'] = float(stats_map['freeThrowsAttempted'])
                elif 'freeThrows' in stats_map:
                    raw = stats_map['freeThrows']
                    if "-" in raw: t_stats['fta'] = float(raw.split('-')[1])
                
                # 3. REBOUNDS
                if 'offensiveRebounds' in stats_map:
                    t_stats['orb'] = float(stats_map['offensiveRebounds'])
                
                # 4. TURNOVERS
                if 'turnovers' in stats_map:
                    t_stats['tov'] = float(stats_map['turnovers'])
                    
                # 5. FOULS
                if 'fouls' in stats_map:
                    t_stats['fouls'] = float(stats_map['fouls'])
                
                # Add this team's totals to the game totals
                game_stats['fga'] += t_stats['fga']
                game_stats['fta'] += t_stats['fta']
                game_stats['orb'] += t_stats['orb']
                game_stats['tov'] += t_stats['tov']
                game_stats['fouls'] += t_stats['fouls']

        # B. ODDS BACKUP
        if 'pickcenter' in res:
            for p in res['pickcenter']:
                if 'overUnder' in p:
                    try:
                        v = float(p['overUnder'])
                        if v > 100: 
                            game_stats['deep_line'] = v
                            break
                    except: continue
        return game_stats
    except: return game_stats

# --- STEP 3: EXECUTION ---
with st.spinner("Refining Calculations..."):
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
            deep = fetch_deep_stats(game['id'], league_choice)
            
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
            
            # Game Pace
            proj_pace = (raw_poss / mins) * FULL_TIME
            
            # Efficiency
            current_eff = total / raw_poss if raw_poss > 0 else 0
            
            # Regression Logic (Sanity Check)
            if use_regression and raw_poss > 0:
                weight = min(mins / FULL_TIME, 1.0)
                final_eff = (current_eff * weight) + (AVG_EFF * (1 - weight))
            else:
                final_eff = current_eff
            
            # Ref Bonus
            fpm = deep['fouls'] / mins
            ref_adj = (fpm - 1.2) * 8.0 if fpm > 1.2 else 0 
            
            # Final Projection
            proj = (proj_pace * final_eff) + ref_adj
            
            edge = round(proj - final_line, 1) if final_line > 0 and proj > 0 else -999.0
            
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")

            results.append({
                "ID": game['id'],
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": f"{p_str} {game['clock_display']}",
                "Fouls": int(deep['fouls']),
                "Pace": round(proj_pace / 2, 1), # Team Pace
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
        
        edited_df = st.data_editor(
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
        
        for index, row in edited_df.iterrows():
            if row['Line'] > 0 and row['Line'] != st.session_state.sticky_lines.get(row['ID']):
                st.session_state.sticky_lines[row['ID']] = row['Line']
