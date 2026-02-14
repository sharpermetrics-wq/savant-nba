import streamlit as st
import pandas as pd
import requests
import time
import re
from apify_client import ApifyClient

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v43: Iron-Clad", layout="wide")
st.title("🏀 Savant v43: The Iron-Clad Hybrid")

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

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Controls")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA"])
    
    st.divider()
    st.markdown("### 💰 Live Odds (Apify)")
    if st.button("🔴 FETCH FANDUEL LINES", type="primary"):
        st.session_state.trigger_apify = True
        st.rerun()
    st.caption(f"Last Update: {st.session_state.last_apify_run}")
    
    st.divider()
    fav_threshold = st.slider("Heavy Fav Threshold", -25.0, -1.0, -6.5, 0.5)
    
    if st.button("🔄 REFRESH GAME DATA", type="secondary"):
        st.rerun()

# --- HELPER: NAME NORMALIZER ---
def normalize_name(name):
    name = name.lower()
    name = re.sub(r'\(\d+\)', '', name)
    name = name.replace("university", "").replace("college", "").replace("state", "st").strip()
    replacements = {
        "ole miss": "mississippi",
        "uconn": "connecticut",
        "massachusetts": "umass",
        "miami (fl)": "miami",
        "miami (oh)": "miami oh",
        "nc st": "north carolina st",
        "n.c. st": "north carolina st",
        "st. john's": "st johns",
        "saint john's": "st johns"
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
        run_input = {
            "league": sport_key,
            "sportsbook": "FanDuel",
            "market": "total"
        }
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
                new_odds[h_team] = line
                new_odds[a_team] = line
        
        status_box.update(label=f"✅ Updated {len(new_odds)} Lines!", state="complete", expanded=False)
        return new_odds
        
    except Exception as e:
        status_box.update(label="❌ Apify Error", state="error")
        st.error(f"Apify Failed: {e}")
        return {}

# --- TRIGGER APIFY ---
if st.session_state.get('trigger_apify'):
    odds_data = fetch_apify_odds(league_choice)
    if odds_data:
        st.session_state.apify_odds = odds_data
        st.session_state.last_apify_run = time.strftime("%H:%M:%S")
    st.session_state.trigger_apify = False

# --- STEP 1: FETCH GAMES (ESPN) ---
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
        events = res.get('events', [])
        for event in events:
            if event['status']['type']['state'] == 'in':
                comp = event['competitions'][0]
                home = comp['competitors'][0]
                away = comp['competitors'][1]
                
                spread = 0.0
                fav_team = ""
                try:
                    for odd in comp.get('odds', []):
                        if 'details' in odd:
                            match = re.search(r'([A-Z]+)\s+(-\d+\.?\d*)', odd['details'])
                            if match: fav_team = match.group(1); spread = float(match.group(2))
                except: pass

                games.append({
                    "id": event['id'],
                    "matchup": event['name'],
                    "clock_display": event['status']['displayClock'],
                    "period": event['status']['period'],
                    "home_score": int(home['score']),
                    "away_score": int(away['score']),
                    "home_team": home['team']['displayName'],
                    "away_team": away['team']['displayName'],
                    "home_abb": home['team']['abbreviation'],
                    "away_abb": away['team']['abbreviation'],
                    "spread": spread,
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
                    nm = stat.get('name', '').lower(); lbl = stat.get('label', '').lower()
                    val = 0.0
                    try:
                        raw = stat.get('displayValue', '0')
                        if "-" in raw: val = float(raw.split('-')[1])
                        else: val = float(raw)
                    except: val = 0.0
                    if "foul" in nm or "pf" in lbl: data['fouls'] += val
                    if "offensive" in nm or "orb" in lbl: data['orb'] += val
                    if "turnover" in nm or "to" in lbl: data['tov'] += val
                    if ("field" in nm or "fg" in lbl) and not ("three" in nm or "3pt" in lbl): data['fga'] += val
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
live_games = fetch_game_data(league_choice)

if not live_games:
    st.info(f"No active {league_choice} games found.")
else:
    progress = st.progress(0)
    results = []
    FULL_TIME = 48.0 if league_choice == "NBA" else 40.0
    
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
            
            # --- 3-LAYER LINE LOGIC ---
            final_line = 0.0
            source_tag = "---"
            
            # 1. APIFY
            h_norm = normalize_name(game['home_team'])
            a_norm = normalize_name(game['away_team'])
            
            if h_norm in st.session_state.apify_odds:
                final_line = st.session_state.apify_odds[h_norm]
                source_tag = "Live (FD)"
            elif a_norm in st.session_state.apify_odds:
                final_line = st.session_state.apify_odds[a_norm]
                source_tag = "Live (FD)"
            
            # 2. STICKY
            sticky = st.session_state.sticky_lines.get(game['id'], 0.0)
            if sticky > 0:
                final_line = sticky
                source_tag = "Manual"
                
            # 3. GHOST
            if final_line == 0.0:
                if deep['deep_total'] > 100 and game['id'] not in st.session_state.opening_totals:
                    st.session_state.opening_totals[game['id']] = deep['deep_total']
                
                opener = st.session_state.opening_totals.get(game['id'], 145.0)
                
                curr_score = game['home_score'] + game['away_score']
                rem_time = FULL_TIME - mins
                final_line = curr_score + (opener * (rem_time / FULL_TIME))
                source_tag = "Ghost"

            # --- SAVANT MATH ---
            total_score = game['home_score'] + game['away_score']
            base_proj = (total_score / mins) * FULL_TIME
            fpm = deep['fouls'] / mins
            ref_adj = (fpm - 1.0) * 8.0 if fpm > 1.0 else 0 
            
            # Comeback Logic
            comeback_adj = 0.0
            status = ""
            is_second_half = (league_choice == "NBA" and p >= 3) or (league_choice != "NBA" and p >= 2)
            if is_second_half and game['spread'] <= fav_threshold:
                fav_score = 0; dog_score = 0
                if game['fav_team'] == game['home_abb']:
                    fav_score = game['home_score']; dog_score = game['away_score']
                elif game['fav_team'] == game['away_abb']:
                    fav_score = game['away_score']; dog_score = game['home_score']
                
                deficit = dog_score - fav_score
                if deficit > 0:
                    comeback_adj = deficit * 0.5
                    status = f"⚠️ {game['fav_team']} Down {deficit}"

            # Volatility
            raw_poss = deep['fga'] - deep['orb'] + deep['tov'] + (0.44 * deep['fta'])
            if raw_poss < 1: raw_poss = 1
            ppp = total_score / raw_poss
            vol_flag = "🔥" if ppp > 1.30 else ("❄️" if ppp < 0.85 else "-")

            # Final Proj
            proj = base_proj + ref_adj + comeback_adj
            
            # Close Game Tax
            score_diff = abs(game['home_score'] - game['away_score'])
            if is_second_half and score_diff <= 6:
                proj += 4.0
            
            edge = round(proj - final_line, 1)

            results.append({
                "ID": game['id'],
                "Matchup": game['matchup'],
                "Score": f"{game['away_score']}-{game['home_score']}",
                "Time": f"Q{p} {game['clock_display']}" if league_choice == "NBA" else f"{p}H {game['clock_display']}",
                "Line": round(final_line, 1),
                "Source": source_tag,
                "Savant": round(proj, 1),
                "EDGE": edge,
                "Vol": vol_flag,
                "Alert": status,
                "SortEdge": abs(edge)
            })

    progress.empty()

    if results:
        df = pd.DataFrame(results)
        df = df.sort_values('SortEdge', ascending=False)
        
        st.data_editor(
            df,
            column_config={
                "Line": st.column_config.NumberColumn("Line (Edit)", required=True, format="%.1f"),
                "Source": st.column_config.TextColumn("Source"),
                "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
                "Savant": st.column_config.NumberColumn("Proj", format="%.1f"),
                "Vol": st.column_config.TextColumn("Vol"),
                "Alert": st.column_config.TextColumn("Alerts"),
                "ID": None,
                "SortEdge": None
            },
            disabled=["Matchup", "Score", "Time", "Source", "Vol", "Alert", "Savant", "EDGE"],
            use_container_width=True,
            hide_index=True
        )
        
        for index, row in st.session_state.get('data_editor', {}).get('edited_rows', {}).items():
            if row['Line'] > 0 and row['Line'] != st.session_state.sticky_lines.get(row['ID']):
                st.session_state.sticky_lines[row['ID']] = row['Line']
