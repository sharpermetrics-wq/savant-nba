import streamlit as st
import pandas as pd
import requests
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v32: Regression Model", layout="wide")
st.title("🏀 Savant v32: The Regression Engine")

# --- MEMORY ---
if 'sticky_lines' not in st.session_state:
    st.session_state.sticky_lines = {} 

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    # REGRESSION TOGGLE
    use_regression = st.toggle("Apply Regression?", value=True, 
        help="If ON, blends current shooting % with league average. If OFF, assumes current shooting continues forever (Linear).")
    
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

# --- STEP 2: DEEP STATS ---
def fetch_deep_stats(game_id, league):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    
    data = {"fouls":0, "fga":0, "fta":0, "orb":0, "tov":0, "deep_line": 0.0}
    try:
        res = requests.get(url, timeout=4).json()
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                for stat in team.get('statistics', []):
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
                    is_fg = ("field" in nm or "fg" in lbl)
                    is_3pt = ("three" in nm or "3pt" in lbl)
                    if is_fg and not is_3pt: data['fga'] += val
                    if "free" in nm or "ft" in lbl: data['fta'] += val
        
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
with st.spinner("Applying Regression Model..."):
    live_games = fetch_game_data(league_choice)

if not live_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress = st.progress(0)
    results = []
    
    # LEAGUE CONSTANTS
    if league_choice == "NBA":
        FULL_TIME = 48.0
        AVG_EFF = 1.12 # NBA Points Per Possession Avg
    else:
        FULL_TIME = 40.0
        AVG_EFF = 1.04 # NCAA Points Per Possession Avg
    
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
            
            curr = game['api_line']
            if curr == 0.0: curr = deep['deep_line']
            mem = st.session_state.sticky_lines.get(game['id'], 0.0)
            
            final_line = 0.0
            if mem > 0: final_line = mem
            elif curr > 0: 
                final_line = curr
                st.session_state.sticky_lines[game['id']] = final_line

            # --- SAVANT V32 MATH ---
            total = game['home'] + game['away']
            
            # 1. Possessions (The Truth)
            # FGA - ORB + TOV + 0.44*FTA
            raw_poss = deep['fga'] - deep['orb'] + deep['tov'] + (0.44 * deep['fta'])
            
            # 2. Pace (Projected Total Possessions)
            # This relies on the pace CONTINUING at current speed
            proj_pace = (raw_poss / mins) * FULL_TIME
            
            # 3. Efficiency (Points Per Possession)
            current_eff = total / raw_poss if raw_poss > 0 else 0
            
            # 4. Regression Logic
            # If enabled, we blend Current Efficiency with League Avg
            # Weight shifts towards current as game goes on
            if use_regression and raw_poss > 0:
                # Weight factor: How much to trust current game? (0.0 to 1.0)
                # Early game: trust Avg more. Late game: trust Current more.
                weight = min(mins / FULL_TIME, 1.0) 
                
                # Blend: (Current * Weight) + (Avg * (1-Weight))
                final_eff = (current_eff * weight) + (AVG_EFF * (1 - weight))
            else:
                final_eff = current_eff # Linear (Old Way)
            
            # 5. Ref Bonus
            fpm = deep['fouls'] / mins
            ref_adj = (fpm - 1.2) * 8.0 if fpm > 1.2 else 0 # Slightly reduced multiplier
            
            # 6. FINAL PROJECTION
            # Proj = (Projected_Pace * Regressed_Efficiency) + Ref_Bonus
            # Now Pace actually matters!
            proj = (proj_pace * final_eff) + ref_adj
            
            edge = round(proj - final_line, 1) if final_line > 0 and proj > 0 else -999.0
            
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")

            results.append({
                "ID": game['id'],
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": f"{p_str} {game['clock_display']}",
                "Fouls": int(deep['fouls']),
                "Pace": round(proj_pace / 2, 1), 
                "PPP": round(current_eff, 2), # Show their current efficiency
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
                "PPP": st.column_config.NumberColumn("PPP", format="%.2f", help="Points Per Possession (League Avg ~1.04)"),
                "ID": None
            },
            disabled=["Matchup", "Score", "Time", "Fouls", "Pace", "PPP", "Savant Proj", "EDGE"],
            use_container_width=True,
            hide_index=True
        )
        
        # Save Edits
        for index, row in edited_df.iterrows():
            if row['Line'] > 0 and row['Line'] != st.session_state.sticky_lines.get(row['ID']):
                st.session_state.sticky_lines[row['ID']] = row['Line']
