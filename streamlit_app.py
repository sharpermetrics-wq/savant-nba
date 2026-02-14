import streamlit as st
import pandas as pd
import requests

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v14: Deep Stats", layout="wide")
st.title("🏀 Savant v14: Advanced Metrics (Fouls & Pace)")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    # CONFIGURATION
    if league_choice == "NBA":
        LEAGUE_URL = "basketball/nba"
        FULL_TIME = 48.0
        # NBA Pace Formula Factor
        PACE_COEFF = 1.12
    else:
        LEAGUE_URL = "basketball/mens-college-basketball"
        FULL_TIME = 40.0
        PACE_COEFF = 1.08

    st.divider()
    if st.button("🚀 PULL DEEP STATS", type="primary"):
        st.rerun()

# --- STEP 1: GET LIVE GAMES LIST ---
def get_live_games():
    url = f"http://site.api.espn.com/apis/site/v2/sports/{LEAGUE_URL}/scoreboard"
    try:
        res = requests.get(url, timeout=8).json()
        games = []
        for event in res.get('events', []):
            status = event['status']['type']['state']
            if status == 'in': # Only active games
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_display": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home_team": event['competitions'][0]['competitors'][0]['team']['displayName'],
                    "home_score": int(event['competitions'][0]['competitors'][0]['score']),
                    "away_team": event['competitions'][0]['competitors'][1]['team']['displayName'],
                    "away_score": int(event['competitions'][0]['competitors'][1]['score']),
                    # Grab Odds if available
                    "line": float(event['competitions'][0]['odds'][0]['overUnder']) if 'odds' in event['competitions'][0] else 0
                })
        return games
    except: return []

# --- STEP 2: GET BOX SCORE (THE DEEP DIVE) ---
def get_game_stats(game_id):
    # This hits the specific game summary to get Fouls, FGA, etc.
    url = f"http://site.api.espn.com/apis/site/v2/sports/{LEAGUE_URL}/summary?event={game_id}"
    try:
        res = requests.get(url, timeout=5).json()
        box = res.get('boxscore', {})
        
        # We need to sum up stats for both teams
        stats = {"fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0}
        
        if 'teams' in box:
            for team in box['teams']:
                # Iterate through statistics list to find specific labels
                for stat in team.get('statistics', []):
                    label = stat['name']
                    value = float(stat['displayValue'])
                    
                    if label == "fouls": stats['fouls'] += value
                    if label == "fieldGoalsAttempted": stats['fga'] += value
                    if label == "freeThrowsAttempted": stats['fta'] += value
                    if label == "offensiveRebounds": stats['orb'] += value
                    if label == "turnovers": stats['tov'] += value
        
        return stats
    except:
        return {"fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0}

# --- STEP 3: THE SAVANT ENGINE ---
with st.spinner("Crunching Box Scores & Foul Counts..."):
    live_feed = get_live_games()
    results = []

    for game in live_feed:
        # 1. Calculate Time Played
        try:
            m, s = map(int, game['clock_display'].split(':'))
        except: m, s = 0, 0
        
        period = game['period']
        
        # NCAA Clock Logic
        if "College" in league_choice:
            if period == 1: mins = 20.0 - m - (s/60)
            elif period == 2: mins = 20.0 + (20.0 - m - (s/60))
            else: mins = 40.0 + ((period-2)*5) - m - (s/60)
        # NBA Clock Logic
        else:
            if period <= 4: mins = ((period-1)*12) + (12 - m - (s/60))
            else: mins = 48.0 + ((period-4)*5) - m - (s/60)

        if mins > 2.0:
            # 2. FETCH DEEP STATS
            stats = get_game_stats(game['id'])
            
            # 3. CALCULATE METRICS
            total_score = game['home_score'] + game['away_score']
            
            # A. Ref Factor (Fouls Per Minute)
            fpm = stats['fouls'] / mins
            
            # B. True Possessions (The Savant Formula)
            # Poss = FGA - ORB + TOV + (0.44 * FTA)
            possessions = stats['fga'] - stats['orb'] + stats['tov'] + (0.44 * stats['fta'])
            
            # C. Pace (Possessions Per Minute)
            pace = possessions / mins if mins > 0 else 0
            
            # D. Efficiency (Points Per Possession)
            off_rtg = total_score / possessions if possessions > 0 else 0
            
            # 4. FINAL PROJECTION
            # Proj = (Pace * Full_Time) * Off_Rtg
            # We apply the 'Ref Adjustment' if FPM is high (> 1.2)
            ref_boost = 0
            if fpm > 1.2: ref_boost = (fpm - 1.2) * 8.0 # Add points for choppy game
            
            proj = (pace * FULL_TIME * off_rtg) + ref_boost
            
            # Edge Calculation
            line = game['line']
            edge = proj - line if line > 0 else 0

            results.append({
                "Matchup": game['matchup'],
                "Score": f"{game['away_score']}-{game['home_score']}",
                "Time": f"{round(mins,1)}m",
                "Fouls": int(stats['fouls']),
                "FPM": round(fpm, 2),
                "Pace": round(pace * FULL_TIME, 1), # Pace per game
                "Proj": round(proj, 1),
                "Line": line if line > 0 else "---",
                "EDGE": round(edge, 1) if line > 0 else "N/A"
            })

# --- DISPLAY ---
if results:
    st.success(f"Deep Analysis on {len(results)} Games")
    df = pd.DataFrame(results)
    
    # Sort by Edge Magnitude
    if "EDGE" in df.columns and len(df) > 0:
        df['sort'] = pd.to_numeric(df['EDGE'], errors='coerce').abs()
        df = df.sort_values('sort', ascending=False).drop(columns=['sort'])
        
    st.table(df)
    
    st.info("💡 **Metric Key:** FPM (Fouls Per Minute) > 1.2 indicates a 'whistle-heavy' game, which inflates scoring.")
else:
    st.warning(f"No active {league_choice} games found.")
