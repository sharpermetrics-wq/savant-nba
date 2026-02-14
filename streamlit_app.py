import streamlit as st
import pandas as pd
import requests
import time
from apify_client import ApifyClient
from difflib import SequenceMatcher

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v27: The Hybrid", layout="wide")
st.title("🏀 Savant v27: The Hybrid Engine (ESPN + Apify)")

# --- SETUP ---
try:
    # We need the token back for this to work
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("⚠️ APIFY_TOKEN missing! Add it to Streamlit Secrets to use this version.")
    st.stop()

# --- SESSION STATE ---
if 'live_odds' not in st.session_state:
    st.session_state.live_odds = {} # Stores {team_name: line}
if 'last_run' not in st.session_state:
    st.session_state.last_run = "Never"

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        # FREE BUTTON
        if st.button("🔄 UPDATE SCORES", type="secondary"):
            st.rerun()
    with col2:
        # PAID BUTTON
        if st.button("💰 FETCH ODDS", type="primary"):
            st.session_state.trigger_apify = True
            st.rerun()
            
    st.caption(f"Last Odds Update: {st.session_state.last_run}")
    st.info("ℹ️ 'Update Scores' is free. 'Fetch Odds' uses Apify credits.")

# --- HELPER: FUZZY MATCH ---
def similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# --- STEP 1: FETCH APIFY ODDS (The Costly Part) ---
def fetch_apify_odds(league):
    client = ApifyClient(APIFY_TOKEN)
    
    # Map selection to Apify codes
    apify_league = "college-basketball" if league == "College (NCAAB)" else "nba"
    
    status_box = st.status("Connecting to FanDuel via Apify...", expanded=True)
    try:
        # Run the scraper
        run_input = {
            "league": apify_league,
            "sportsbook": "fanduel",
            "market": "total" # Focus on totals
        }
        
        # Start the actor
        status_box.write("🚀 Launching Scraper...")
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input=run_input)
        
        status_box.write("📦 Downloading Dataset...")
        new_odds = {}
        
        # Parse results
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            team = item.get('homeTeam', 'Unknown')
            
            # Extract Over/Under
            # Apify structure varies, usually list of odds
            line = 0.0
            for odd in item.get('odds', []):
                if odd.get('type') == 'overUnder':
                    line = float(odd.get('overUnder', 0.0))
                    break
            
            if line > 100:
                new_odds[team] = line
        
        status_box.update(label="✅ Odds Updated!", state="complete", expanded=False)
        return new_odds
        
    except Exception as e:
        status_box.update(label="❌ Apify Failed", state="error")
        st.error(f"Apify Error: {e}")
        return {}

# --- TRIGGER LOGIC ---
if st.session_state.get('trigger_apify'):
    with st.spinner("Fetching fresh lines from FanDuel..."):
        odds_data = fetch_apify_odds(league_choice)
        if odds_data:
            st.session_state.live_odds = odds_data
            st.session_state.last_run = time.strftime("%H:%M:%S")
    st.session_state.trigger_apify = False

# --- STEP 2: FETCH ESPN SCORES (The Free Part) ---
def fetch_espn_data(league):
    ts = int(time.time())
    if league == "NBA":
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100&t={ts}"
    else:
        url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000&t={ts}"
    
    try:
        res = requests.get(url, timeout=5).json()
        games = []
        for event in res.get('events', []):
            if event['status']['type']['state'] == 'in':
                comp = event['competitions'][0]
                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "home": comp['competitors'][0]['team']['displayName'],
                    "away": comp['competitors'][1]['team']['displayName'],
                    "home_score": int(comp['competitors'][0]['score']),
                    "away_score": int(comp['competitors'][1]['score']),
                    "clock": event['status']['displayClock'],
                    "period": event['status']['period']
                })
        return games
    except: return []

# --- STEP 3: DEEP STATS ---
def get_deep_stats(game_id, league):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    
    data = {"fouls":0, "pace_stats": {"fga":0, "fta":0, "orb":0, "tov":0}}
    try:
        res = requests.get(url, timeout=3).json()
        if 'boxscore' in res and 'teams' in res['boxscore']:
            for team in res['boxscore']['teams']:
                for stat in team.get('statistics', []):
                    val = 0.0
                    try:
                        raw = stat.get('displayValue','0')
                        val = float(raw.split('-')[1]) if '-' in raw else float(raw)
                    except: val = 0.0
                    
                    nm = stat.get('name','').lower()
                    if "foul" in nm: data['fouls'] += val
                    if "field" in nm: data['pace_stats']['fga'] += val
                    if "free" in nm: data['pace_stats']['fta'] += val
                    if "offensive" in nm: data['pace_stats']['orb'] += val
                    if "turnover" in nm: data['pace_stats']['tov'] += val
        return data
    except: return data

# --- MAIN ENGINE ---
live_games = fetch_espn_data(league_choice)

if not live_games:
    st.info(f"No active {league_choice} games found.")
else:
    # Only show progress if we are scanning games
    results = []
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
    # Progress bar for the deep stats scan
    bar = st.progress(0)
    
    for i, game in enumerate(live_games):
        bar.progress((i + 1) / len(live_games))
        
        # 1. Parse Clock
        try:
            if ":" in game['clock']: m, s = map(int, game['clock'].split(':'))
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
            # 2. Match Apify Odds (The Fuzzy Logic)
            odds_line = 0.0
            
            # Check if we have any odds from Apify
            if st.session_state.live_odds:
                # Try exact match first
                if game['home'] in st.session_state.live_odds:
                    odds_line = st.session_state.live_odds[game['home']]
                else:
                    # Try fuzzy match (e.g. "Ohio" vs "Ohio Bobcats")
                    best_match = None
                    highest_score = 0.0
                    
                    for k, v in st.session_state.live_odds.items():
                        score = similar(game['home'], k)
                        if score > 0.6 and score > highest_score:
                            highest_score = score
                            best_match = v
                    
                    if best_match:
                        odds_line = best_match

            # 3. Deep Stats
            deep = get_deep_stats(game['id'], league_choice)
            
            # 4. Math
            total = game['home_score'] + game['away_score']
            fpm = deep['fouls'] / mins
            stats = deep['pace_stats']
            poss = stats['fga'] - stats['orb'] + stats['tov'] + (0.44 * stats['fta'])
            pace = poss / mins
            off_rtg = total / poss if poss > 0 else 0
            
            ref_adj = (fpm - 1.2) * 10.0 if fpm > 1.2 else 0
            proj = (pace * FULL_TIME * off_rtg) + ref_adj
            
            edge = round(proj - odds_line, 1) if odds_line > 0 else -999.0
            
            # Formatting
            p_str = f"Q{p}" if league_choice == "NBA" else (f"{p}H" if p <= 2 else f"OT{p-2}")

            results.append({
                "Matchup": game['matchup'],
                "Score": f"{game['away_score']}-{game['home_score']}",
                "Time": f"{p_str} {game['clock']}",
                "Fouls": int(deep['fouls']),
                "FPM": round(fpm, 2),
                "Line": odds_line,
                "Savant Proj": round(proj, 1),
                "EDGE": edge,
            })

    bar.empty()
    
    if results:
        df = pd.DataFrame(results)
        
        # Sort by Edge
        df['sort_val'] = df['EDGE'].apply(lambda x: abs(x) if x != -999 else 0)
        df = df.sort_values('sort_val', ascending=False).drop(columns=['sort_val'])
        
        st.data_editor(
            df,
            column_config={
                "Line": st.column_config.NumberColumn("Line (FanDuel)", format="%.1f"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant Proj": st.column_config.NumberColumn("Proj", format="%.1f"),
                "FPM": st.column_config.NumberColumn("FPM", format="%.2f"),
            },
            disabled=["Matchup", "Score", "Time", "Fouls", "FPM", "Savant Proj", "EDGE"],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("No games in progress.")
