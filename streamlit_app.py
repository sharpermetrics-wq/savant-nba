import streamlit as st
import pandas as pd
import requests

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v17: Action Mode", layout="wide")
st.title("🏀 Savant v17: Direct Action Mode")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🚀 SCAN MARKET", type="primary"):
        st.rerun()

# --- STEP 1: GET ACTIVE GAMES (DEEP SCAN) ---
def get_live_games(league):
    # Set the URL and the FanDuel Link based on league
    if league == "NBA":
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100"
        fd_url = "https://sportsbook.fanduel.com/navigation/nba"
    else:
        # groups=50 unlocks ALL Division I games
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000"
        fd_url = "https://sportsbook.fanduel.com/navigation/ncaab"
    
    try:
        res = requests.get(url, timeout=10).json()
        games = []
        
        for event in res.get('events', []):
            comp = event['competitions'][0]
            status = event['status']['type']['state']
            
            if status == 'in':
                # --- ODDS FIX: Scan ALL providers, not just the first one ---
                line = 0.0
                if 'odds' in comp:
                    for odd_provider in comp['odds']:
                        if 'overUnder' in odd_provider:
                            try:
                                line = float(odd_provider['overUnder'])
                                break # Stop once we find a valid line
                            except: continue
                
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home_score": int(comp['competitors'][0]['score']),
                    "away_score": int(comp['competitors'][1]['score']),
                    "line": line,
                    "fd_link": fd_url # The direct link to FanDuel
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
                    # Robust parsing for "20-55" format
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
with st.spinner("Analyzing Live Games..."):
    active_games = get_live_games(league_choice)

if not active_games:
    st.info(f"No active {league_choice} games found.")
else:
    # Progress bar for deep scanning
    progress_bar = st.progress(0)
    results = []
    
    # Constants
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    for i, game in enumerate(active_games):
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
            box = get_box_stats(game['id'], league_choice)
            
            total = game['home_score'] + game['away_score']
            fpm = box['fouls'] / mins
            poss = box['fga'] - box['orb'] + box['tov'] + (0.44 * box['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            # Ref Adjustment
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            line = game['line']
            edge = proj - line if line > 0 else 0

            results.append({
                "Matchup": game['matchup'],
                "Score": f"{game['away_score']}-{game['home_score']}",
                "Clock": f"P{game['period']} {game['clock']}",
                "FPM": round(fpm, 2),
                "Savant Proj": round(proj, 1),
                "Bookie Line": line if line > 0 else "---",
                "EDGE": round(edge, 1) if line > 0 else -999, # -999 for sorting if no line
                "Action": game['fd_link']
            })
            
    progress_bar.empty()

    if results:
        df = pd.DataFrame(results)
        
        # Sort by absolute edge size
        if not df.empty:
            df['sort'] = df['EDGE'].abs()
            df = df.sort_values('sort', ascending=False).drop(columns=['sort'])
            
            # Replace the -999 placeholder with "N/A" for display
            df['EDGE'] = df['EDGE'].apply(lambda x: x if x != -999 else "N/A")

        # --- DISPLAY WITH CLICKABLE LINKS ---
        st.dataframe(
            df,
            column_config={
                "Action": st.column_config.LinkColumn(
                    "Bet Now",
                    help="Open FanDuel Live",
                    display_text="Open FanDuel 📲"
                ),
                "EDGE": st.column_config.NumberColumn(
                    "Edge",
                    format="%.1f",
                )
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("Games found, but none have passed the 2-minute threshold.")
