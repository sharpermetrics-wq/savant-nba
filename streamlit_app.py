import streamlit as st
import pandas as pd
import requests

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v16: Mid-Major Hunter", layout="wide")
st.title("🏀 Savant v16: The 'Mid-Major' Hunter")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🚀 SCAN ALL DIV-I GAMES", type="primary"):
        st.rerun()

# --- STEP 1: GET ALL ACTIVE GAMES (UNFILTERED) ---
def get_live_games(league):
    if league == "NBA":
        # NBA doesn't need groups, just a high limit
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100"
    else:
        # THE FIX: groups=50 unlocks ALL Division I games (not just Top 25)
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000"
    
    try:
        res = requests.get(url, timeout=10).json()
        games = []
        
        for event in res.get('events', []):
            comp = event['competitions'][0]
            status = event['status']['type']['state']
            
            # Only process active games ('in')
            if status == 'in':
                # Get Odds (Try/Except to handle missing lines)
                line = 0.0
                if 'odds' in comp:
                    try:
                        line = float(comp['odds'][0].get('overUnder', 0))
                    except: line = 0.0
                
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home_score": int(comp['competitors'][0]['score']),
                    "away_score": int(comp['competitors'][1]['score']),
                    "line": line
                })
        return games
    except: return []

# --- STEP 2: GET BOX SCORE ---
def get_box_stats(game_id, league):
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}"
    
    # Default Stats
    stats = {"fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0}
    
    try:
        res = requests.get(url, timeout=5).json()
        if 'boxscore' not in res or 'teams' not in res['boxscore']:
            return stats
            
        for team in res['boxscore']['teams']:
            for stat in team.get('statistics', []):
                name = stat.get('name', '').lower()
                label = stat.get('label', '').lower()
                val = 0.0
                try:
                    raw_val = stat.get('displayValue', '0')
                    if "-" in raw_val: val = float(raw_val.split('-')[1]) # "20-50" -> 50
                    else: val = float(raw_val)
                except: val = 0.0
                
                if "foul" in name or "pf" in label: stats['fouls'] += val
                if "fieldgoals" in name or "fg" in label: stats['fga'] += val
                if "freethrows" in name or "ft" in label: stats['fta'] += val
                if "offensive" in name or "orb" in label: stats['orb'] += val
                if "turnover" in name or "to" in label: stats['tov'] += val
        return stats
    except: return stats

# --- STEP 3: THE ENGINE ---
# We use a progress bar because scanning 50+ mid-major games takes time
with st.spinner("Initializing Deep Scan..."):
    active_games = get_live_games(league_choice)

if not active_games:
    st.info(f"No active {league_choice} games found.")
else:
    st.success(f"Found {len(active_games)} Active Games. Pulling Box Scores...")
    
    results = []
    # Progress Bar for user sanity
    progress_bar = st.progress(0)
    
    if league_choice == "NBA":
        FULL_TIME = 48.0
        COEFF = 1.12
    else:
        FULL_TIME = 40.0
        COEFF = 1.08

    for i, game in enumerate(active_games):
        # Update progress
        progress_bar.progress((i + 1) / len(active_games))
        
        # 1. Parse Clock
        try:
            if ":" in game['clock']: m, s = map(int, game['clock'].split(':'))
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
            # 2. Get Deep Stats
            box = get_box_stats(game['id'], league_choice)
            
            # 3. Savant Math
            total_score = game['home_score'] + game['away_score']
            fpm = box['fouls'] / mins
            poss = box['fga'] - box['orb'] + box['tov'] + (0.44 * box['fta'])
            pace = poss / mins
            off_rtg = total_score / poss if poss > 0 else 0
            
            # Ref Adjustment
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            line = game['line']
            edge = proj - line if line > 0 else 0

            results.append({
                "Matchup": game['matchup'],
                "Score": f"{game['away_score']}-{game['home_score']}",
                "Clock": f"P{game['period']} {game['clock']}",
                "Fouls": int(box['fouls']),
                "FPM": round(fpm, 2),
                "Pace": round(pace * FULL_TIME, 1),
                "Savant Proj": round(proj, 1),
                "Line": line if line > 0 else "---",
                "EDGE": round(edge, 1) if line > 0 else "N/A"
            })
            
    progress_bar.empty() # Clear bar when done

    # --- DISPLAY ---
    if results:
        df = pd.DataFrame(results)
        
        # Smart Sort: Put the biggest EDGE at the top
        if "EDGE" in df.columns and not df.empty:
            df['sort'] = pd.to_numeric(df['EDGE'], errors='coerce').abs()
            df = df.sort_values('sort', ascending=False).drop(columns=['sort'])
            
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.warning("Games found, but none have passed the 2-minute warm-up threshold.")
