import streamlit as st
import pandas as pd
import requests
import time
import re
from apify_client import ApifyClient
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v50: Force Sync", layout="wide")
st.title("🏀 Savant v50: The Sync Fix")

# --- SECRETS & SETUP ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    APIFY_TOKEN = st.sidebar.text_input("Enter Apify API Token:", type="password")

# --- MEMORY ---
if 'sticky_lines' not in st.session_state:
    st.session_state.sticky_lines = {} 
if 'opening_totals' not in st.session_state:
    st.session_state.opening_totals = {}
if 'apify_odds' not in st.session_state:
    st.session_state.apify_odds = {} 
if 'last_apify_run' not in st.session_state:
    st.session_state.last_apify_run = "Never"
if 'bet_slip' not in st.session_state:
    st.session_state.bet_slip = []

# --- HELPER: NAME NORMALIZER ---
def normalize_name(name):
    name = name.lower()
    name = re.sub(r'\(\d+\)', '', name)
    name = name.replace("university", "").replace("college", "").replace("state", "st").strip()
    replacements = {
        "ole miss": "mississippi", "uconn": "connecticut", "massachusetts": "umass",
        "miami (fl)": "miami", "miami (oh)": "miami oh", "nc st": "north carolina st",
        "n.c. st": "north carolina st", "st. john's": "st johns", "saint john's": "st johns"
    }
    return replacements.get(name, name)

# --- HELPER: APIFY FETCH ---
def fetch_apify_odds(league):
    if not APIFY_TOKEN:
        st.sidebar.error("⚠️ No Apify Token Found!")
        return {}
    client = ApifyClient(APIFY_TOKEN)
    sport_key = "College-Basketball" if league == "College (NCAAB)" else "NBA"
    
    status_box = st.status("Connecting to FanDuel...", expanded=True)
    try:
        status_box.write("🚀 Launching Scraper...")
        run_input = {"league": sport_key, "sportsbook": "FanDuel", "market": "total"}
        run = client.actor("harvest/sportsbook-odds-scraper").call(run_input=run_input)
        status_box.write("📦 Downloading Lines...")
        new_odds = {}
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            line = 0.0
            if 'odds' in item:
                for odd in item['odds']:
                    if odd.get('type') == 'overUnder' or 'overUnder' in odd:
                        try:
                            val = float(odd.get('overUnder', 0.0))
                            if val > 100: line = val
                        except: pass
            if line == 0.0 and 'overUnder' in item:
                try: line = float(item['overUnder'])
                except: pass

            if line > 100:
                h_team = normalize_name(item.get('homeTeam', 'Unknown'))
                a_team = normalize_name(item.get('awayTeam', 'Unknown'))
                new_odds[h_team] = line; new_odds[a_team] = line
        status_box.update(label=f"✅ Updated {len(new_odds)} Lines!", state="complete", expanded=False)
        return new_odds
    except Exception as e:
        status_box.update(label="❌ Apify Error", state="error")
        st.error(f"Apify Failed: {e}")
        return {}

# --- TRIGGER APIFY ---
if st.session_state.get('trigger_apify'):
    odds_data = fetch_apify_odds(st.session_state.get('league_choice', 'College (NCAAB)'))
    if odds_data:
        st.session_state.apify_odds = odds_data
        st.session_state.last_apify_run = time.strftime("%H:%M:%S")
    st.session_state.trigger_apify = False

# --- FETCH & PARSE LOGIC ---
def fetch_data(league):
    ts = int(time.time())
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?limit=100&t={ts}" if league == "NBA" else f"http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=1000&t={ts}"
    try:
        return requests.get(url, headers={"Cache-Control": "no-cache"}, timeout=8).json()
    except: return {}

def fetch_deep(game_id, league):
    ts = int(time.time())
    sport = "nba" if league == "NBA" else "mens-college-basketball"
    url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/summary?event={game_id}&t={ts}"
    try: return requests.get(url, timeout=4).json()
    except: return {}

# --- CONTROLS (TOP SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Controls")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"], key="league_choice")
    if st.button("🔴 FETCH FANDUEL LINES", type="primary"):
        st.session_state.trigger_apify = True
        st.rerun()
    st.caption(f"Last FD Update: {st.session_state.last_apify_run}")
    
    fav_threshold = st.slider("Heavy Fav Threshold", -25.0, -1.0, -6.5, 0.5)
    
    st.divider()
    if st.button("🔄 REFRESH DATA", type="primary"):
        st.rerun()

# --- MAIN EXECUTION ---
data = fetch_data(league_choice)
live_games = []
events = data.get('events', [])
if events:
    for event in events:
        if event['status']['type']['state'] == 'in':
            comp = event['competitions'][0]
            spread = 0.0; fav_team = ""
            try:
                for odd in comp.get('odds', []):
                    if 'details' in odd:
                        match = re.search(r'([A-Z]+)\s+(-\d+\.?\d*)', odd['details'])
                        if match: fav_team = match.group(1); spread = float(match.group(2))
            except: pass
            
            live_games.append({
                "id": str(event['id']), # FORCE STRING ID
                "matchup": event['name'],
                "clock": event['status']['displayClock'],
                "period": event['status']['period'],
                "home": int(comp['competitors'][0]['score']),
                "away": int(comp['competitors'][1]['score']),
                "home_team": comp['competitors'][0]['team']['displayName'],
                "away_team": comp['competitors'][1]['team']['displayName'],
                "home_abb": comp['competitors'][0]['team']['abbreviation'],
                "away_abb": comp['competitors'][1]['team']['abbreviation'],
                "spread": spread, "fav_team": fav_team
            })

# --- PROCESSING ---
results = []
live_game_map = {} 

if live_games:
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    progress = st.progress(0)
    
    for i, game in enumerate(live_games):
        progress.progress((i + 1) / len(live_games))
        
        try:
            if ":" in game['clock']: m, s = map(int
