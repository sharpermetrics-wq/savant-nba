import streamlit as st
import pandas as pd
import requests
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v38: Nuanced Comeback", layout="wide")
st.title("🏀 Savant v38: The Nuanced Comeback")

# --- MEMORY ---
if 'sticky_lines' not in st.session_state:
    st.session_state.sticky_lines = {} 

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    # PARAMETERS
    fav_threshold = st.slider("Heavy Favorite Threshold", -25.0, -1.0, -6.5, 0.5,
        help="Spread must be this number or lower (e.g. -7) to trigger logic.")
    
    if st.button("🔄 REFRESH DATA", type="primary"):
        st.rerun()
    
    st.divider()
    st.markdown("""
    **🔥 Comeback Logic (v38):**
    If Heavy Fav is losing in 2nd Half:
    1. **Fav Boost:** +100% of Deficit (They chase)
    2. **Dog Drag:** -50% of Deficit (They cool off)
    3. **Net Effect:** Total + (Deficit * 0.5)
    """)

# --- HELPER: ODDS PARSER ---
def parse_odds_data(comp):
    total = 0.0
    spread = 0.0
    fav = ""
    
    if 'odds' in comp:
        for odd in comp['odds']:
            if total == 0.0 and 'overUnder' in odd:
                try: 
                    val = float(odd['overUnder'])
                    if val > 100: total = val
                except: pass
            
            if spread == 0.0 and 'details' in odd:
                txt = odd['details'] 
                match = re.search(r'([A-Z]+)\s+(-\d+\.?\d*)', txt)
                if match:
                    fav = match.group(1)
                    spread = float(match.group(2))
    return total, spread, fav

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
                api_total, api_spread, fav_team = parse_odds_data(comp)
                home = comp['competitors'][0]
                away = comp['competitors'][1]
                
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_display": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home_score": int(home['score']),
                    "away_score": int(away['score']),
                    "home_abb": home['team']['abbreviation'],
                    "away_abb": away['team']['abbreviation'],
                    "api_total": api_total,
                    "spread": api_spread,
                    "fav_team": fav_team
                })
        return games
    except: return []

# --- STEP 2: DEEP STATS ---
def fetch_deep_stats(game_id, league):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    
    data = {"fouls":0, "fga":0, "fta":0, "orb":0, "tov":0, "deep_total": 0.0}
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
                    if ("field" in nm or "fg" in lbl) and not ("three" in nm or "3pt" in lbl):
                        data['fga'] += val
                    if "free" in nm or "ft" in lbl: data['fta'] += val
        
        if 'pickcenter' in res:
            for p in res['pickcenter']:
                if 'overUnder' in p:
                    try:
                        v = float(p['overUnder'])
                        if v > 100: data['deep_total'] = v; break
                    except: continue
        return data
    except: return data

# --- STEP 3: EXECUTION ---
with st.spinner("Analyzing Momentum..."):
    live_games = fetch_game_data(league_choice)

if not live_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress = st.progress(0)
    results = []
    
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    for i, game in enumerate(live_games):
        progress.progress((i + 1) / len(live_games))
        
        # Clock
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
            curr = game['api_total']
            if curr == 0.0: curr = deep['deep_total']
            mem = st.session_state.sticky_lines.get(game['id'], 0.0)
            final_line = mem if mem > 0 else curr
            if final_line > 0: st.session_state.sticky_lines[game['id']] = final_line

            # --- MATH ---
            total_score = game['home_score'] + game['away_score']
            
            # 1. Base Proj
            base_proj = (total_score / mins) * FULL_TIME
            
            # 2. Ref Bonus (Standard)
            fpm = deep['fouls'] / mins
            ref_adj = (fpm - 1.0) * 8.0 if fpm > 1.0 else 0 
            
            # 3. COMEBACK ENGINE v38 (The Nuanced Mix)
            comeback_adj = 0.0
            status = ""
            
            is_second_half = (league_choice == "NBA" and p >= 3) or (league_choice != "NBA" and p >= 2)
            
            if is_second_half and game['spread'] <= fav_threshold:
                # Calculate Deficit
                fav_score = 0
                dog_score = 0
                if game['fav_team'] == game['home_abb']:
                    fav_score = game['home_score']; dog_score = game['away_score']
                elif game['fav_team'] == game['away_abb']:
                    fav_score = game['away_score']; dog_score = game['home_score']
                
                deficit = dog_score - fav_score
                
                if deficit > 0:
                    # THE FORMULA:
                    # Fav Score Boost = +Deficit (They chase)
                    # Dog Score Drag = -(Deficit * 0.5) (They tighten up/regress)
                    # Net Total Impact = +0.5 * Deficit
                    comeback_adj = deficit * 0.5
                    status = f"⚠️ {game['fav_team']} Down {deficit}"

            # 4. Final
            proj = base_proj + ref_adj + comeback_adj
            
            # 5. Close Game Tax (Still applies if VERY close)
            score_diff = abs(game['home_score'] - game['away_score'])
            if is_second_half and score_diff <= 6: # Tightened to 6 pts
                proj += 4.0 # Tightened to 4 pts
            
            edge = round(proj - final_line, 1) if final_line > 0 else -999.0
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")

            results.append({
                "ID": game['id'],
                "Matchup": game['matchup'],
                "Score": f"{game['away_score']}-{game['home_score']}",
                "Time": f"{p_str} {game['clock_display']}",
                "Line": final_line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge,
                "Spread": game['spread'],
                "Alert": status
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
                "Spread": st.column_config.NumberColumn("Spread", format="%.1f"),
                "Alert": st.column_config.TextColumn("Situation"),
                "ID": None
            },
            disabled=["Matchup", "Score", "Time", "Spread", "Alert", "Savant Proj", "EDGE"],
            use_container_width=True,
            hide_index=True
        )
        
        for index, row in st.session_state.get('data_editor', {}).get('edited_rows', {}).items():
            pass
