import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import smtplib
import google.generativeai as genai
from datetime import datetime, timedelta
from email.message import EmailMessage
import plotly.graph_objects as go

# --- 1. CONFIG ---
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY")
ALPHA_KEY = st.secrets.get("ALPHA_KEY")
SENDER_EMAIL = st.secrets.get("SENDER_EMAIL")
SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# --- 2. ENGINES ---
def get_stock_details(ticker):
    try:
        df = yf.download(ticker, period="60d", progress=False)
        if df.empty: return None
        
        curr = float(df['Close'].iloc[-1])
        p5 = float(df['Close'].iloc[-5])
        p30 = float(df['Close'].iloc[-22])
        
        perf = {
            "Current": f"${curr:.2f}",
            "5-Day": f"${p5:.2f} ({((curr-p5)/p5)*100:+.2f}%)",
            "30-Day": f"${p30:.2f} ({((curr-p30)/p30)*100:+.2f}%)"
        }
        return {"curr": curr, "df": df, "perf": perf}
    except: return None

def get_ai_analysis(ticker, headline):
    if not GEMINI_KEY: return "🔑 MISSING KEY"
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Stock: {ticker}. News: {headline}. Give 1 emoji and 5 words on outlook."
        response = model.generate_content(prompt)
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
            data = get_stock_details(t)
            
            # News Fetch
            news_url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={t}&apikey={ALPHA_KEY}"
            try:
                r = requests.get(news_url).json()
                news_h = r.get("feed", [{}])[0].get("title", "No Recent News")
                news_s = r.get("feed", [{}])[0].get("summary", "")
            except: news_h, news_s = "News Offline", ""

            if data:
                ai_val = get_ai_analysis(t, news_h)
                
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.metric(f"{t} Price", data['perf']['Current'])
                    st.write(f"**AI SIGNAL:** {ai_val}")
                    st.table(pd.DataFrame([data['perf']], index=["Price History"]))

                with c2:
                    # BAR CHART instead of Line
                    fig = go.Figure(data=[go.Bar(
                        x=data['df'].index, 
                        y=data['df']['Close'],
                        marker_color='#00d4ff'
                    )])
                    fig.update_layout(
                        title=f"{t} Price History (Bar View)", 
                        template="plotly_dark", 
                        height=350,
                        xaxis_title="Date",
                        yaxis_title="Close Price ($)"
                    )
                    st.plotly_chart(fig, use_container_width=True)

                st.write(f"**Latest News:** {news_h}")
                st.caption(news_s)

                # Email
                if SENDER_EMAIL and SENDER_PASSWORD:
                    msg = EmailMessage()
                    msg["Subject"] = f"STOCK ALERT: {t} {ai_val}"
                    msg["From"] = SENDER_EMAIL
                    msg["To"] = SENDER_EMAIL
                    msg.set_content(f"Analysis for {t}\nAI: {ai_val}\n\nPrices:\n{data['perf']}\n\nNews: {news_h}")
                    try:
                        with smtplib.SMTP('smtp.gmail.com', 587) as server:
                            server.starttls()
                            server.login(SENDER_EMAIL, SENDER_PASSWORD)
                            server.send_message(msg)
                    except: pass
            else:
                st.error(f"Data for {t} not found.")
