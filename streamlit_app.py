import streamlit as st
import pandas as pd
import requests

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v15: Deep Search", layout="wide")
st.title("🏀 Savant v15: Deep Stats Automation")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🚀 REFRESH DATA", type="primary"):
        st.rerun()

# --- STEP 1: GET ACTIVE GAMES ---
def get_live_games(league):
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard"
    
    try:
        res = requests.get(url, timeout=10).json()
        games = []
        
        for event in res.get('events', []):
            comp = event['competitions'][0]
            status = event['status']['type']['state']
            
            # Only process active games
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

# --- STEP 2: GET BOX SCORE (The Fix) ---
def get_box_stats(game_id, league):
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}"
    
    # Default Stats
    stats = {"fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0}
    
    try:
        res = requests.get(url, timeout=5).json()
        if 'boxscore' not in res or 'teams' not in res['boxscore']:
            return stats
            
        # Iterate through both teams
        for team in res['boxscore']['teams']:
            # The 'statistics' block is a list of objects. We must search by 'name' or 'label'.
            for stat in team.get('statistics', []):
                name = stat.get('name', '').lower()
                label = stat.get('label', '').lower()
                val = 0.0
                
                try:
                    # Clean up the display value (remove dashes, etc.)
                    raw_val = stat.get('displayValue', '0')
                    
                    # Case 1: Shooting Stats (e.g. "20-50") -> We want the attempts (50)
                    if "-" in raw_val:
                        val = float(raw_val.split('-')[1])
                    else:
                        val = float(raw_val)
                except: val = 0.0
                
                # Match Keys
                if "foul" in name or "pf" in label: stats['fouls'] += val
                if "fieldgoals" in name or "fg" in label: stats['fga'] += val
                if "freethrows" in name or "ft" in label: stats['fta'] += val
                if "offensive" in name or "orb" in label: stats['orb'] += val
                if "turnover" in name or "to" in label: stats['tov'] += val
                
        return stats
    except:
        return stats

# --- STEP 3: THE ENGINE ---
with st.spinner("Analyzing Live Box Scores..."):
    active_games = get_live_games(league_choice)
    results = []
    
    # Config Constants
    if league_choice == "NBA":
        FULL_TIME = 48.0
        COEFF = 1.12
    else:
        FULL_TIME = 40.0
        COEFF = 1.08

    for game in active_games:
        # 1. Parse Clock
        try:
            if ":" in game['clock']:
                m, s = map(int, game['clock'].split(':'))
            else: m, s = 0, 0
            
            p = game['period']
            
            # Mins Played Logic
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
            
            # Ref Factor (FPM)
            fpm = box['fouls'] / mins
            
            # True Possessions
            # FGA - ORB + TOV + (0.44 * FTA)
            poss = box['fga'] - box['orb'] + box['tov'] + (0.44 * box['fta'])
            
            # Pace (Poss per minute)
            pace = poss / mins
            
            # Projection
            off_rtg = total_score / poss if poss > 0 else 0
            
            # Ref Adjustment: If FPM > 1.2, add penalty boost
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            # Edge
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

# --- DISPLAY ---
if results:
    st.success(f"Tracking {len(results)} Live Games")
    df = pd.DataFrame(results)
    
    # Sort by Edge Magnitude
    if "EDGE" in df.columns and not df.empty:
        df['sort'] = pd.to_numeric(df['EDGE'], errors='coerce').abs()
        df = df.sort_values('sort', ascending=False).drop(columns=['sort'])
        
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info(f"No active {league_choice} games found.")
