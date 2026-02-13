import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import smtplib
import google.generativeai as genai
from datetime import datetime, timedelta
from email.message import EmailMessage
import plotly.graph_objects as go

# --- 1. CONFIG & SEC MAPPING ---
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY")
ALPHA_KEY = st.secrets.get("ALPHA_KEY")
SENDER_EMAIL = st.secrets.get("SENDER_EMAIL")
SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD")

SEC_FORM_MAP = {
    "4": "Insider Trading",
    "5": "Insider Trading (Annual)",
    "144": "Intent to Sell Stock",
    "10-Q": "Quarterly Financial Report",
    "10-K": "Annual Financial Report",
    "8-K": "Material Event Report",
    "S-1": "Registration Statement (IPO)",
    "S-3": "Registration Statement (Secondary)",
    "S-4": "Registration Statement (Merger/Exchange)",
    "SC 13G": "Passive Ownership Change",
    "SC 13D": "Active Ownership Change",
    "DEFA14A": "Proxy Solicitation",
    "DEF 14A": "Official Proxy Statement",
    "6-K": "Foreign Issuer Material Event"
}

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# --- 2. DATA ENGINES ---
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="45d")
        if df.empty: return None
        
        # Snapshots
        curr_p = float(df['Close'].iloc[-1])
        p5_p = float(df['Close'].iloc[-5])
        p10_p = float(df['Close'].iloc[-10])
        p30_p = float(df['Close'].iloc[-22])

        plot_df = pd.DataFrame({
            "Timeline": ["30 Days Ago", "10 Days Ago", "5 Days Ago", "Current"],
            "Price": [p30_p, p10_p, p5_p, curr_p]
        })

        # SEC Filings Fetcher
        filings = []
        try:
            sec_data = stock.actions # Getting corporate actions as proxy for recent events
            # Note: For true SEC feeds, we use the news feed filtered for SEC sources
        except: pass

        return {"curr": curr_p, "plot_df": plot_df, "info": stock.info}
    except: return None

def get_ai_analysis(ticker, headline):
    if not GEMINI_KEY: return "🔑 KEY MISSING"
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(f"Analyze {ticker} news: {headline}. 1 emoji + 5 words.")
        return response.text.strip()
    except: return "⚪ AI BUSY"

# --- 3. UI ---
st.set_page_config(page_title="Stock Watch AI", layout="wide")
st.title("📈 Stock Watch AI Console")

ticker_input = st.text_input("Enter Tickers", "VZ, TSLA, AAPL")
tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]

if st.button("🚀 RUN FULL ANALYSIS"):
    for t in tickers:
        with st.container(border=True):
            data = get_stock_data(t)
            
            # Fetch News & SEC Filings via Alpha Vantage
            news_url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={t}&apikey={ALPHA_KEY}"
            sec_filings = []
            try:
                r = requests.get(news_url).json()
                feed = r.get("feed", [])
                news_h = feed[0].get("title", "No Recent News")
                news_s = feed[0].get("summary", "")
                
                # Filter news feed for SEC-related keywords to simulate the Filing Feed
                for item in feed[:10]:
                    title = item.get("title", "").upper()
                    for form_code, label in SEC_FORM_MAP.items():
                        if f"FORM {form_code}" in title or label.upper() in title:
                            sec_filings.append(f"{label} (Detected in News)")
                            break
            except: news_h, news_s = "News Offline", ""

            if data:
                ai_val = get_ai_analysis(t, news_h)
                st.subheader(f"Snapshot: {t}")
                
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.metric("Price", f"${data['curr']:.2f}")
                    st.write(f"**AI SIGNAL:** {ai_val}")
                    
                    # --- RESTORED SEC FEED ---
                    st.write("**Recent SEC Filing Feed:**")
                    if sec_filings:
                        for filing in list(set(sec_filings))[:3]:
                            st.success(f"📄 {filing}")
                    else:
                        st.info("No major SEC forms detected in recent news.")

                with c2:
                    # SOLID COLOR 4-BAR GRAPH
                    fig = go.Figure(data=[go.Bar(
                        x=data['plot_df']["Timeline"], 
                        y=data['plot_df']["Price"],
                        marker_color=['#1f77b4', '#d62728', '#ff7f0e', '#2ca02c'], 
                        text=[f"${x:.2f}" for x in data['plot_df']["Price"]],
                        textposition='outside',
                    )])
                    fig.update_layout(
                        title=f"{t} Price Benchmarks",
                        template="plotly_dark",
                        height=350,
                        yaxis=dict(range=[min(data['plot_df']["Price"]) * 0.95, max(data['plot_df']["Price"]) * 1.05])
                    )
                    st.plotly_chart(fig, use_container_width=True)

                st.write(f"**Latest News:** {news_h}")
                st.caption(news_s)
            else:
                st.error(f"Error loading {t}")
