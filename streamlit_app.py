import os, json, requests, warnings, smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

import pandas as pd
import yfinance as yf
import google.generativeai as genai
from flask import Flask, request, render_template_string, redirect
from google.cloud import firestore

# --- INITIALIZATION ---
warnings.filterwarnings("ignore", category=FutureWarning)
app = Flask(__name__)
db = firestore.Client()

# SEC Form Translation Mapping (Your Original Logic)
SEC_FORM_MAP = {
    "4": "Insider Trading", "8-K": "Material Event", "10-Q": "Quarterly Report",
    "10-K": "Annual Report", "SC 13G": "Ownership Change", "S-1": "IPO/Registration"
}

# Config from Environment
TICKER_DOC = db.collection("settings").document("tickers")
FIELD = "active_tickers"
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
FINNHUB_KEY = os.environ.get("FINNHUB_KEY")
ALPHA_KEY = os.environ.get("ALPHA_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")

# --- 1. THE DATA ENGINE (PRICE ANALYSIS) ---
def get_detailed_price_history(ticker):
    """Calculates Current, 5, 10, and 30 day prices as requested."""
    try:
        # Fetch 45 days to ensure we have enough trading days for the 30-day offset
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=45)
        data = yf.download(ticker, start=start_dt, end=end_dt, progress=False)
        
        if data.empty: return "Price data unavailable."
        
        # Get the most recent price (Current)
        current_p = float(data['Close'].iloc[-1])
        
        def get_offset_price(days_back):
            target_date = (end_dt - timedelta(days=days_back)).date()
            # Find the closest date in the index
            idx = data.index.get_indexer([pd.Timestamp(target_date)], method='nearest')[0]
            return float(data['Close'].iloc[idx])

        p5 = get_offset_price(5)
        p10 = get_offset_price(10)
        p30 = get_offset_price(30)

        def fmt(p_old, p_curr):
            diff = ((p_curr - p_old) / p_old) * 100
            return f"${p_old:.2f} ({diff:+.2f}%)"

        return (f"Current: ${current_p:.2f}\n"
                f"5-Day Ago: {fmt(p5, current_p)}\n"
                f"10-Day Ago: {fmt(p10, current_p)}\n"
                f"30-Day Ago: {fmt(p30, current_p)}")
    except Exception as e:
        return f"Error fetching prices: {str(e)}"

# --- 2. THE AI JUDGMENT ENGINE ---
def get_ai_judgment(ticker, news, filing):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Analyze {ticker}. News: {news}. SEC Filing: {filing}. Return emoji + 5-word sentiment."
        response = model.generate_content(prompt)
        return response.text.strip() if response.text else "⚪ NEUTRAL"
    except:
        return "⚪ NEUTRAL (AI Timeout)"

# --- 3. BROWSER INTERFACE (HTML/IO) ---
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Stock Event Console</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 40px auto; background: #f4f7f9; line-height: 1.6; }
        .card { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 20px; }
        .ticker { display: inline-block; background: #e1f5fe; color: #0288d1; padding: 5px 12px; border-radius: 15px; margin: 5px; font-weight: bold; }
        input[type="text"] { width: 70%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; }
        button { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-blue { background: #007bff; color: white; }
        .btn-green { background: #28a745; color: white; width: 100%; font-size: 1.2em; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Dashboard Control</h2>
        <form action="/command" method="post">
            <input type="text" name="cmd" placeholder="Type /add TICKER or /remove TICKER">
            <button type="submit" class="btn-blue">Execute</button>
        </form>
        <div style="margin-top: 20px;">
            {% for t in tickers %}<span class="ticker">{{ t }}</span>{% endfor %}
        </div>
    </div>
    <div class="card">
        <h2>Manual Execution</h2>
        <p>Trigger the full analysis (AI Judgment + 30-day Price Trends) right now:</p>
        <a href="/check"><button class="btn-green">RUN FULL REPORT</button></a>
    </div>
</body>
</html>
"""

@app.route("/")
def index():
    doc = TICKER_DOC.get()
    tickers = doc.to_dict().get(FIELD, []) if doc.exists else []
    return render_template_string(HTML_PAGE, tickers=tickers)

@app.route("/command", methods=["POST"])
def handle_command():
    raw = request.form.get("cmd", "").strip().split()
    if len(raw) >= 2:
        action, ticker = raw[0].lower(), raw[1].upper()
        if action == "/add": TICKER_DOC.set({FIELD: firestore.ArrayUnion([ticker])}, merge=True)
        if action == "/remove": TICKER_DOC.update({FIELD: firestore.ArrayRemove([ticker])})
    return redirect("/")

@app.route("/check")
def check():
    tickers = TICKER_DOC.get().to_dict().get(FIELD, [])
    for t in tickers:
        # Get News
        news_resp = requests.get(f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={t}&apikey={ALPHA_KEY}").json()
        headline = news_resp.get('feed', [{}])[0].get('title', 'No recent news')
        
        # Get Detailed Prices (Current, 5, 10, 30)
        price_report = get_detailed_price_history(t)
        
        # Get AI Judgment
        sentiment = get_ai_judgment(t, headline, "Standard Review")
        
        # Send Consolidated Email
        msg = EmailMessage()
        msg["Subject"] = f"ANALYSIS: {t} {sentiment[:15]}"
        msg["From"] = SENDER_EMAIL
        msg["To"] = SENDER_EMAIL
        msg.set_content(f"AI JUDGMENT: {sentiment}\n\nPRICE PERFORMANCE:\n{price_report}\n\nLATEST NEWS:\n{headline}")
        
        try:
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.send_message(msg)
        except Exception as e:
            print(f"Mail failed for {t}: {e}")

    return "<h1>Success</h1><p>Reports for all tickers sent to your email.</p><a href='/'>Back to Dashboard</a>"

if __name__ == "__main__":
    # REQUIRED: This starts the web server so you can use it in a browser
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
