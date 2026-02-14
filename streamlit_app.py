import streamlit as st
import pandas as pd
import requests
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v22: Live Priority", layout="wide")
st.title("🏀 Savant v22: Scoreboard Priority")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    if st.button("🔄 FORCE LIVE UPDATE", type="primary"):
        st.rerun()
    
    st.caption("ℹ️ If lines are static, ESPN is sending 'Closing Lines'. Edit the table manually for live accuracy.")

# --- STEP 1: GET LIVE GAMES & ODDS (The "Fast Lane") ---
def get_live_data(league):
    ts = int(time.time()) # Cache Buster
    
    if league == "NBA":
        # Limit 100 to get everyone
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100&t={ts}"
        fd_url = "https://sportsbook.fanduel.com/navigation/nba"
    else:
        # Groups=50 for All Div I
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000&t={ts}"
        fd_url = "https://sportsbook.fanduel.com/navigation/ncaab"
    
    try:
        # Headers to prevent caching
        headers = {
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
        res = requests.get(url, headers=headers, timeout=8).json()
        games = []
        
        for event in res.get('events', []):
            if event['status']['type']['state'] == 'in':
                comp = event['competitions'][0]
                
                # --- ODDS EXTRACTION (Scoreboard Source) ---
                # This is often 'fresher' than the summary endpoint
                line = 0.0
                book = "---"
                
                if 'odds' in comp:
                    for odd in comp['odds']:
                        # Look for a valid O/U
                        if 'overUnder' in odd:
                            try:
                                val = float(odd['overUnder'])
                                if val > 100:
                                    line = val
                                    book = odd.get('provider', {}).get('name', 'ESPN')
                                    break
                            except: continue
                
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_display": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home": int(comp['competitors'][0]['score']),
                    "away": int(comp['competitors'][1]['score']),
                    "line": line, # From Scoreboard
                    "book": book,
                    "fd_link": fd_url
                })
        return games
    except Exception as e:
        return []

# --- STEP 2: GET DEEP STATS (Box Source) ---
def get_deep_stats(game_id, league):
    ts = int(time.time())
    sport_path = "basketball/nba" if league == "NBA" else "basketball/mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}&t={ts}"
    
    data = {"fouls": 0, "fga": 0, "fta": 0, "orb": 0, "tov": 0}
    
    try:
        res = requests.get(url, timeout=4).json()
        
        # We ONLY look for stats here now, not odds (speed optimization)
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                for stat in team.get('statistics', []):
                    val = 0.0
                    try:
                        raw = stat.get('displayValue', '0')
                        val = float(raw.split('-')[1]) if "-" in raw else float(raw)
                    except: val = 0.0
                    
                    nm = stat.get('name', '').lower()
                    lbl = stat.get('label', '').lower()
                    
                    if "foul" in nm or "pf" in lbl: data['fouls'] += val
                    if "field" in nm or "fg" in lbl: data['fga'] += val
                    if "free" in nm or "ft" in lbl: data['fta'] += val
                    if "offensive" in nm or "orb" in lbl: data['orb'] += val
                    if "turnover" in nm or "to" in lbl: data['tov'] += val
        return data
    except: return data

# --- STEP 3: EXECUTION ---
with st.spinner("Pinging Live Scoreboard..."):
    active_games = get_live_data(league_choice)

if not active_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress_bar = st.progress(0)
    results = []
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    for i, game in enumerate(active_games):
        progress_bar.progress((i + 1) / len(active_games))
        
        # Clock Logic
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
            # Fetch Box Score
            stats = get_deep_stats(game['id'], league_choice)
            
            total = game['home'] + game['away']
            fpm = stats['fouls'] / mins
            poss = stats['fga'] - stats['orb'] + stats['tov'] + (0.44 * stats['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            line = game['line']
            edge = round(proj - line, 1) if line > 0 else -999.0
            
            # Formatted Clock
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")
            clean_clock = f"{p_str} {game['clock_display']}"

            results.append({
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Clock": clean_clock,
                "Book": game['book'],
                "Line": line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge,
                "Link": game['fd_link']
            })
            
    progress_bar.empty()

    if results:
        df = pd.DataFrame(results)
        
        # Sort
        df['sort_val'] = df['EDGE'].apply(lambda x: abs(x) if x != -999 else 0)
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])
        
        st.data_editor(
            df,
            column_config={
                "Link": st.column_config.LinkColumn("Bet", display_text="FanDuel 📲"),
                "Line": st.column_config.NumberColumn("Line (Edit)", required=True, format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Book": st.column_config.TextColumn("Source", disabled=True),
                "Clock": st.column_config.TextColumn("Time", disabled=True)
            },
            disabled=["Matchup", "Score", "Clock", "Book", "Savant Proj", "EDGE", "Link"],
            use_container_width=True,
            hide_index=True
        )
