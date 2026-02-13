import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import smtplib
import google.generativeai as genai
from datetime import datetime, timedelta
from email.message import EmailMessage

# --- 1. SECRETS CHECK ---
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY")
ALPHA_KEY = st.secrets.get("ALPHA_KEY")
SENDER_EMAIL = st.secrets.get("SENDER_EMAIL")
SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# --- 2. DATA ENGINES ---
def get_stock_data(ticker):
    try:
        data = yf.download(ticker, period="45d", progress=False)
        if data.empty: return None
        curr = float(data['Close'].iloc[-1])
        p5 = float(data['Close'].iloc[-5])
        p30 = float(data['Close'].iloc[-22]) # Approx 30 days
        return {"curr": curr, "p5": p5, "p30": p30}
    except: return None

def get_news_and_ai(ticker):
    # Fetch News from Alpha Vantage
    news_url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={ALPHA_KEY}"
    try:
        r = requests.get(news_url).json()
        feed = r.get("feed", [])
        headline = feed[0].get("title", "No recent news found.") if feed else "No recent news found."
        summary = feed[0].get("summary", "") if feed else ""
    except:
        headline, summary = "News Service Unavailable", ""

    # Get AI Judgment
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Stock: {ticker}. News: {headline}. Provide 1 emoji and a 5-word forecast."
        response = model.generate_content(prompt)
        judgment = response.text.strip()
    except:
        judgment = "⚪ AI OFFLINE"
        
    return headline, summary, judgment

# --- 3. DASHBOARD UI ---
st.title("📈 Stock Watch AI Console")

ticker_input = st.text_input("Enter Tickers", "AAPL, VZ, TSLA")
tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]

if st.button("🚀 RUN FULL REPORT & EMAIL"):
    for t in tickers:
        with st.expander(f"RESULTS FOR {t}", expanded=True):
            # Get Data
            prices = get_stock_data(t)
            news_h, news_s, ai_val = get_news_and_ai(t)
            
            if prices:
                col1, col2 = st.columns(2)
                col1.metric(f"{t} Price", f"${prices['curr']:.2f}")
                col2.write(f"**AI SIGNAL:** {ai_val}")
                
                st.write(f"**Latest News:** {news_h}")
                st.caption(news_s)
                
                # Email Logic
                if SENDER_EMAIL and SENDER_PASSWORD:
                    msg = EmailMessage()
                    msg["Subject"] = f"ALERT: {t} - {ai_val}"
                    msg["From"] = SENDER_EMAIL
                    msg["To"] = SENDER_EMAIL
                    msg.set_content(f"Price: ${prices['curr']:.2f}\nAI: {ai_val}\n\nNews: {news_h}\n{news_s}")
                    try:
                        with smtplib.SMTP('smtp.gmail.com', 587) as server:
                            server.starttls()
                            server.login(SENDER_EMAIL, SENDER_PASSWORD)
                            server.send_message(msg)
                        st.success(f"Email sent for {t}!")
                    except:
                        st.error("Email failed. Check your App Password.")
            else:
                st.error(f"Could not find data for {t}")
