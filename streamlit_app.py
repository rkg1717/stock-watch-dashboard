import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import smtplib
import google.generativeai as genai
from datetime import datetime, timedelta
from email.message import EmailMessage

# --- 1. CONFIGURATION ---
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY")
ALPHA_KEY = st.secrets.get("ALPHA_KEY")
SENDER_EMAIL = st.secrets.get("SENDER_EMAIL")
SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# --- 2. YOUR ORIGINAL LOGIC ENGINES ---
def get_detailed_price_history(ticker):
    try:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=45)
        data = yf.download(ticker, start=start_dt, end=end_dt, progress=False)
        if data.empty: return {"current": 0, "report": "Price data unavailable."}
        
        current_p = float(data['Close'].iloc[-1])
        def get_offset_price(days_back):
            target_date = (end_dt - timedelta(days=days_back)).date()
            idx = data.index.get_indexer([pd.Timestamp(target_date)], method='nearest')[0]
            return float(data['Close'].iloc[idx])

        p5, p10, p30 = get_offset_price(5), get_offset_price(10), get_offset_price(30)
        def fmt(p_old, p_curr):
            diff = ((p_curr - p_old) / p_old) * 100
            return f"${p_old:.2f} ({diff:+.2f}%)"

        return {
            "current": current_p,
            "report": f"Current: ${current_p:.2f}\n5-Day: {fmt(p5, current_p)}\n10-Day: {fmt(p10, current_p)}\n30-Day: {fmt(p30, current_p)}"
        }
    except Exception as e:
        return {"current": 0, "report": f"Error: {str(e)}"}

def get_ai_judgment(ticker, news):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Analyze {ticker}. News: {news}. Return emoji + 5-word sentiment."
        response = model.generate_content(prompt)
        return response.text.strip() if response.text else "⚪ NEUTRAL"
    except:
        return "⚪ NEUTRAL (AI Timeout)"

# --- 3. STREAMLIT DASHBOARD UI ---
st.set_page_config(page_title="Stock Watch AI", page_icon="📈")
st.title("📈 Stock Analysis Console")

ticker_input = st.text_input("Enter Ticker Symbols (separated by commas)", "AAPL, VZ, TSLA")
tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]

if st.button("🚀 RUN FULL REPORT & EMAIL"):
    for t in tickers:
        with st.status(f"Analyzing {t}...", expanded=True):
            # 1. News
            news_url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={t}&apikey={ALPHA_KEY}"
            news_resp = requests.get(news_url).json()
            headline = news_resp.get('feed', [{}])[0].get('title', 'No recent news')
            
            # 2. Prices
            price_data = get_detailed_price_history(t)
            
            # 3. AI
            sentiment = get_ai_judgment(t, headline)
            
            # Display
            st.metric(f"{t} Price", f"${price_data['current']:.2f}")
            st.write(f"**AI Signal:** {sentiment}")
            st.text(price_data['report'])

            # 4. Email
            if SENDER_EMAIL and SENDER_PASSWORD:
                msg = EmailMessage()
                msg["Subject"] = f"ANALYSIS: {t} {sentiment[:15]}"
                msg["From"] = SENDER_EMAIL
                msg["To"] = SENDER_EMAIL
                msg.set_content(f"AI JUDGMENT: {sentiment}\n\nPRICE PERFORMANCE:\n{price_data['report']}\n\nLATEST NEWS:\n{headline}")
                try:
                    with smtplib.SMTP('smtp.gmail.com', 587) as server:
                        server.starttls()
                        server.login(SENDER_EMAIL, SENDER_PASSWORD)
                        server.send_message(msg)
                    st.success(f"Email sent for {t}!")
                except Exception as e:
                    st.error(f"Mail failed: {e}")
