import streamlit as st
import pandas as pd
import requests
from apify_client import ApifyClient

# --- SECURE CONFIG ---
try:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
except:
    st.error("Missing APIFY_TOKEN in Secrets!")
    st.stop()

# --- PAGE SETUP ---
st.set_page_config(page_title="Savant v6.5: Validation Fix", layout="wide")
st.title("🏀 Savant v6.5: Validated Automation")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏆 League Selection")
    league_choice = st.selectbox("League", ["College (NCAAB)", "NBA", "EuroLeague", "Brazil NBB"])
    
    # CRITICAL UPDATE: These strings must match the Apify "Allowed Values" exactly
    league_map = {
        "NBA": {"apify_code": "NBA", "score_tag": "NBA", "len": 48, "coeff": 1.12, "auto": True},
        "EuroLeague": {"apify_code": "UCL", "score_tag": "UCL", "len": 40, "coeff": 0.94, "auto": True},
        "Brazil NBB": {"apify_code": "BRAZIL", "score_tag": "BRAZIL", "len": 40, "coeff": 1.02, "auto": False},
        "College (NCAAB)": {"apify_code": "College-Basketball", "score_tag": "NCAA", "len": 40,
