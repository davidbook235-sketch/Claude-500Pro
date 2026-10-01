# 📈 Nifty 500 Pro Scanner

Score 0-100 (trend + momentum + relative strength + breakout/pullback trigger), liquidity/trend filters,
Nifty market-regime check, risk-based position sizing, sector view, aur portfolio-level backtest (Nifty se comparison).

## Chalane ke liye
```bash
pip install -r requirements.txt
streamlit run app.py
```

## GitHub + Streamlit Cloud
1. Is folder ki saari files repo me daalo (purane repo me replace kar sakte ho).
2. share.streamlit.io → New app → repo → Main file `app.py` → Deploy.
3. Auto daily scan: Repo Settings → Actions → General → Workflow permissions: **Read and write**.
4. Telegram alert (optional): BotFather se bot banao, repo Settings → Secrets → Actions me
   `TELEGRAM_BOT_TOKEN` aur `TELEGRAM_CHAT_ID` add karo.

## Notes
- Data yfinance (free, thoda delayed). Nifty 500 list NSE se aati hai; na aaye to `data/nifty500.csv` (columns `Symbol`, `Industry`) daalo.
- Default thresholds uncalibrated hain. Pehle Backtest tab chalao, phir sidebar se tune karo.
- Educational tool, investment advice nahi.
