import streamlit as st
import pandas as pd
import requests
import time
import re
from apify_client import ApifyClient
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Savant v48: Type-Safe", layout="wide")
st.title("🏀 Savant v48: Stability Patch")

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

# --- MAIN EXECUTION ---
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

# --- FETCH DATA ---
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
                "id": event['id'],
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
        
        # --- THE FIX: Type-Safe Clock Logic ---
        try:
            if ":" in game['clock']: m, s = map(int, game['clock'].split(':'))
            else: m, s = 0, 0
            
            # FORCE INTEGER CASTING
            p = int(game['period']) 
            
            mins = 0.0
            if league_choice == "NBA":
                if p <= 4: mins = ((p-1)*12) + (12 - m - (s/60))
                else: mins = 48.0 + ((p-4)*5) - m - (s/60)
            else: 
                if p == 1: mins = 20.0 - m - (s/60)
                elif p == 2: mins = 20.0 + (20.0 - m - (s/60))
                else: mins = 40.0 + ((p-2)*5) - m - (s/60)
        except: 
            mins = 0.0
            p = 1 # Safe default if parsing fails
        
        if mins > 2.0:
            deep_raw = fetch_deep(game['id'], league_choice)
            deep = {"fouls":0, "fga":0, "fta":0, "orb":0, "tov":0, "deep_total": 0.0}
            
            if 'boxscore' in deep_raw and 'teams' in deep_raw['boxscore']:
                for team in deep_raw['boxscore']['teams']:
                    for stat in team.get('statistics', []):
                        nm = stat.get('name', '').lower(); lbl = stat.get('label', '').lower()
                        val = 0.0
                        try:
                            raw = stat.get('displayValue', '0')
                            if "-" in raw: val = float(raw.split('-')[1])
                            else: val = float(raw)
                        except: val = 0.0
                        if "foul" in nm or "pf" in lbl: deep['fouls'] += val
                        if "offensive" in nm or "orb" in lbl: deep['orb'] += val
                        if "turnover" in nm or "to" in lbl: deep['tov'] += val
                        if ("field" in nm or "fg" in lbl) and not ("three" in nm or "3pt" in lbl): deep['fga'] += val
                        if "free" in nm or "ft" in lbl: deep['fta'] += val
            
            if 'pickcenter' in deep_raw:
                for p_idx in deep_raw['pickcenter']:
                    if 'overUnder' in p_idx:
                        try: deep['deep_total'] = float(p_idx['overUnder']); break
                        except: continue

            # LINE LOGIC
            final_line = 0.0
            h_norm = normalize_name(game['home_team']); a_norm = normalize_name(game['away_team'])
            if h_norm in st.session_state.apify_odds: final_line = st.session_state.apify_odds[h_norm]
            elif a_norm in st.session_state.apify_odds: final_line = st.session_state.apify_odds[a_norm]
            
            sticky = st.session_state.sticky_lines.get(game['id'], 0.0)
            if sticky > 0: final_line = sticky
            
            if final_line == 0.0:
                if deep['deep_total'] > 100 and game['id'] not in st.session_state.opening_totals:
                    st.session_state.opening_totals[game['id']] = deep['deep_total']
                opener = st.session_state.opening_totals.get(game['id'], 145.0)
                curr_score = game['home'] + game['away']
                rem = FULL_TIME - mins
                final_line = curr_score + (opener * (rem / FULL_TIME))

            # SAVANT MATH
            total_score = game['home'] + game['away']
            base_proj = (total_score / mins) * FULL_TIME
            fpm = deep['fouls'] / mins
            ref_adj = (fpm - 1.0) * 8.0 if fpm > 1.0 else 0 
            
            comeback_adj = 0.0
            status = ""
            # The line that crashed is now safe because 'p' is strictly an int
            is_second_half = (league_choice == "NBA" and p >= 3) or (league_choice != "NBA" and p >= 2)
            
            if is_second_half and game['spread'] <= fav_threshold:
                fav = 0; dog = 0
                if game['fav_team'] == game['home_abb']: fav = game['home']; dog = game['away']
                elif game['fav_team'] == game['away_abb']: fav = game['away']; dog = game['home']
                deficit = dog - fav
                if deficit > 0:
                    comeback_adj = deficit * 0.5
                    status = f"⚠️ {game['fav_team']} Down {deficit}"
            
            # Volatility (Blind Spot Fix)
            orb_val = deep['orb']
            if orb_val == 0 and deep['fga'] > 0: orb_val = deep['fga'] * 0.20
            raw_poss = deep['fga'] - orb_val + deep['tov'] + (0.44 * deep['fta'])
            if raw_poss < 1: raw_poss = 1
            ppp = total_score / raw_poss
            vol_flag = "🔥" if ppp > 1.25 else ("❄️" if ppp < 0.80 else "-")
            
            proj = base_proj + ref_adj + comeback_adj
            diff = abs(game['home'] - game['away'])
            if is_second_half and diff <= 6: proj += 4.0
            
            edge = round(proj - final_line, 1)
            
            live_game_map[game['id']] = {
                "Score": f"{game['away']}-{game['home']}",
                "Time": f"Q{p} {game['clock']}" if league_choice == "NBA" else f"{p}H {game['clock']}",
                "Proj": round(proj, 1)
            }
            
            is_tracked = False
            for bet in st.session_state.bet_slip:
                if bet['ID'] == game['id']: is_tracked = True; break
            
            results.append({
                "Track": is_tracked,
                "ID": game['id'],
                "Matchup": game['matchup'],
                "Score": f"{game['away']}-{game['home']}",
                "Time": f"Q{p} {game['clock']}" if league_choice == "NBA" else f"{p}H {game['clock']}",
                "Line": round(final_line, 1),
                "Savant": round(proj, 1),
                "EDGE": edge,
                "Vol": vol_flag,
                "Alert": status,
                "SortEdge": abs(edge)
            })
    progress.empty()

# --- SIDEBAR: LIVE BET SLIP ---
with st.sidebar:
    st.divider()
    st.subheader("📝 Live Bet Slip")
    if st.session_state.bet_slip:
        if st.button("🗑️ Clear All Bets"):
            st.session_state.bet_slip = []
            st.rerun()
            
        for bet in st.session_state.bet_slip:
            live_data = live_game_map.get(bet['ID'], {"Score": "Final/HT", "Time": "--", "Proj": 0})
            curr_proj = live_data['Proj']
            status = "⚪"
            if curr_proj > 0:
                if bet['Pick'] == "OVER": status = "✅ WIN" if curr_proj > bet['Line'] else "❌ LOSS"
                else: status = "✅ WIN" if curr_proj < bet['Line'] else "❌ LOSS"
            
            st.markdown(f"**{bet['Matchup']}**")
            st.caption(f"{bet['Pick']} {bet['Line']} | Entry: {bet['Entry_Proj']}")
            st.caption(f"{status} | Live: **{curr_proj}** ({live_data['Score']})")
            st.divider()
    else: st.info("No active bets.")

# --- MAIN DASHBOARD ---
if results:
    df = pd.DataFrame(results).sort_values('SortEdge', ascending=False)
    edited_df = st.data_editor(
        df,
        column_config={
            "Track": st.column_config.CheckboxColumn("Bet?", width="small"),
            "Line": st.column_config.NumberColumn("Line (Edit)", format="%.1f"),
            "EDGE": st.column_config.NumberColumn("Edge", format="%.1f"),
            "Savant": st.column_config.NumberColumn("Proj", format="%.1f"),
            "Vol": st.column_config.TextColumn("Vol", width="small"),
            "Alert": st.column_config.TextColumn("Alerts"),
            "ID": None, "SortEdge": None
        },
        disabled=["Matchup", "Score", "Time", "Vol", "Alert", "Savant", "EDGE"],
        use_container_width=True,
        hide_index=True,
        key="main_dashboard"
    )
    
    for index, row in edited_df.iterrows():
        if row['Line'] > 0 and row['Line'] != st.session_state.sticky_lines.get(row['ID']):
            st.session_state.sticky_lines[row['ID']] = row['Line']
        if row['Track']:
            exists = False
            for bet in st.session_state.bet_slip:
                if bet['ID'] == row['ID']: exists = True; break
            if not exists:
                pick = "OVER" if row['EDGE'] > 0 else "UNDER"
                st.session_state.bet_slip.append({
                    "ID": row['ID'], "Matchup": row['Matchup'], "Pick": pick,
                    "Line": row['Line'], "Entry_Proj": row['Savant']
                })
                st.rerun()
        else:
            for i, bet in enumerate(st.session_state.bet_slip):
                if bet['ID'] == row['ID']:
                    st.session_state.bet_slip.pop(i)
                    st.rerun()
