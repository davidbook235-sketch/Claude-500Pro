import datetime as dt

import plotly.graph_objects as go
import streamlit as st

from scanner.backtest import BTConfig, run_portfolio
from scanner.data import download_index, download_prices, load_universe
from scanner.indicators import Params, add_indicators, regime_series, scan_all

st.set_page_config(page_title="Nifty 500 Pro Scanner", page_icon="📈", layout="wide")
CHUNK = 50
BT_PERIOD = {1: "2y", 2: "5y", 3: "5y", 5: "10y"}   # warm-up (EMA200/52w) ke liye extra history


@st.cache_data(ttl=86400, show_spinner=False)
def get_universe():
    return load_universe()


@st.cache_data(ttl=600, show_spinner=False)
def fetch_chunk(symbols: tuple, period: str):
    return download_prices(list(symbols), period=period)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_index(period: str):
    return download_index(period)


def fetch_all(symbols, period, label):
    bar, prices = st.progress(0.0, text=label), {}
    for i in range(0, len(symbols), CHUNK):
        prices.update(fetch_chunk(tuple(symbols[i:i + CHUNK]), period))
        done = min(i + CHUNK, len(symbols))
        bar.progress(done / len(symbols), text=f"{label} {done}/{len(symbols)}")
    bar.empty()
    return prices


symbols, src, sectors = get_universe()

# ---------------- Sidebar ----------------
sb = st.sidebar
sb.title("⚙️ Settings")
sb.caption(f"Universe: {len(symbols)} stocks · {src}")
with sb.expander("💰 Capital & risk", expanded=True):
    capital = st.number_input("Capital (₹)", 10000, 100000000, 500000, 50000)
    risk_pct = st.number_input("Risk per trade %", 0.1, 5.0, 1.0, 0.1)
    max_pos_pct = st.number_input("Max position % of capital", 5, 100, 20)
with sb.expander("🚦 Filters"):
    min_price = st.number_input("Min price ₹", 0, 5000, 50)
    min_val = st.number_input("Min avg traded value (₹ Cr/day)", 0.0, 500.0, 5.0)
    above200 = st.checkbox("Sirf Close > EMA200", True)
    max_ext = st.number_input("EMA20 se max door %", 3.0, 40.0, 12.0)
    block_weak = st.checkbox("Nifty weak ho to BUY block karo", True)
    min_rs = st.slider("Min RS Rank (0-100)", 0, 95, 0)
with sb.expander("🎯 Thresholds & risk"):
    buy_score = st.slider("BUY min score", 40, 100, 70)
    watch_score = st.slider("WATCH min score", 30, 100, 55)
    atr_mult = st.number_input("StopLoss = ATR ×", 0.5, 5.0, 2.0, 0.25)
    rr = st.number_input("Target Risk:Reward", 1.0, 6.0, 2.5, 0.5)
with sb.expander("📊 Indicators"):
    rsi_lo = st.number_input("RSI >", 40.0, 70.0, 55.0)
    rsi_hi = st.number_input("RSI <= (momentum band)", 60.0, 90.0, 75.0)
    vol_mult = st.number_input("Volume spike ×", 1.0, 5.0, 1.5, 0.1)
    adx_min = st.number_input("ADX >", 10.0, 40.0, 20.0)
    brk = st.number_input("Breakout days", 5, 100, 20)

p = Params(rsi_lo=rsi_lo, rsi_hi=rsi_hi, vol_mult=vol_mult, adx_min=adx_min, breakout_days=int(brk),
           min_price=min_price, min_value_cr=min_val, max_ext_pct=max_ext, require_above_200=above200,
           atr_mult=atr_mult, rr=rr, buy_score=buy_score, watch_score=watch_score)

st.title("📈 Nifty 500 Pro Scanner")
tab_scan, tab_bt, tab_about = st.tabs(["🔍 Scanner", "🧪 Backtest", "ℹ️ Rules"])

# ---------------- Scanner ----------------
with tab_scan:
    c1, c2, c3 = st.columns([2, 1, 1])
    n = c1.slider("Kitne stocks scan karne hain", 20, len(symbols), len(symbols), 10)
    sig_f = c2.multiselect("Signal", ["BUY", "WATCH"], ["BUY", "WATCH"])
    go_scan = c3.button("🔍 Scan now", type="primary", use_container_width=True)
    if c3.button("♻️ Fresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if go_scan:
        nifty = fetch_index("2y")
        reg = regime_series(nifty, p)
        regime_ok = True if reg is None else bool(reg.iloc[-1])
        prices = fetch_all(symbols[:n], "2y", "Data download")
        st.session_state.update(
            prices=prices, nifty=nifty, regime_ok=regime_ok,
            scan=scan_all(prices, p, nifty, sectors, capital, risk_pct, max_pos_pct, regime_ok, block_weak, min_rs),
            scan_time=dt.datetime.now().strftime("%d %b %Y %H:%M:%S"), scan_n=len(prices))

    res = st.session_state.get("scan")
    if res is None:
        st.info("'Scan now' dabao. Market hours me aakhri candle live hoti hai (Yahoo data thoda delayed).")
    else:
        if st.session_state["regime_ok"]:
            st.success("🟢 Market healthy: Nifty apni EMA50 ke upar hai")
        else:
            st.warning("🔴 Market weak: Nifty EMA50 ke neeche. BUY signals WATCH me daale gaye" if block_weak
                       else "🔴 Market weak: Nifty EMA50 ke neeche. Savdhan raho")
        st.caption(f"Last scan: {st.session_state['scan_time']} · {st.session_state['scan_n']} stocks ka data mila")
        if res.empty:
            st.warning("Koi stock in conditions par nahi mila. Filters/thresholds dheele karke dekho.")
        else:
            view = res[res["Signal"].isin(sig_f)]
            m1, m2, m3 = st.columns(3)
            m1.metric("BUY", int((res.Signal == "BUY").sum()))
            m2.metric("WATCH", int((res.Signal == "WATCH").sum()))
            m3.metric("Scanned", st.session_state["scan_n"])
            st.dataframe(view, use_container_width=True, hide_index=True)
            st.download_button("⬇️ CSV download", view.to_csv(index=False), "scan_results.csv", "text/csv")
            if res["Sector"].astype(bool).any():
                st.write("**Sector-wise signals** (kaun sa sector garam hai)")
                st.bar_chart(res[res.Sector != ""].groupby("Sector").size().sort_values(ascending=False).head(12))

            pick = st.selectbox("Chart dekho", view["Symbol"].tolist()) if not view.empty else None
            if pick:
                d = add_indicators(st.session_state["prices"][pick], p, st.session_state["nifty"]).tail(150)
                row = view[view.Symbol == pick].iloc[0]
                fig = go.Figure(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close, name=pick))
                for col, nm in (("ema_f", "EMA20"), ("ema_m", "EMA50"), ("ema_l", "EMA200")):
                    fig.add_scatter(x=d.index, y=d[col], name=nm, line=dict(width=1))
                fig.add_hline(y=row.StopLoss, line_dash="dash", line_color="red")
                fig.add_hline(y=row.Target, line_dash="dash", line_color="green")
                fig.update_layout(height=450, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=20, b=0))
                st.plotly_chart(fig, use_container_width=True)

# ---------------- Backtest ----------------
with tab_bt:
    st.caption("Portfolio backtest: position limits, risk-based sizing, costs, aur Nifty 50 se comparison.")
    a, b, c, d_ = st.columns(4)
    years = a.selectbox("Test period (saal)", [1, 2, 3, 5], index=2)
    bt_score = b.slider("Entry min score", 40, 100, p.buy_score)
    exit_mode = c.selectbox("Exit style", ["Trailing", "Target"])
    max_pos = d_.number_input("Max positions", 1, 30, 8)
    e, f, g, h_ = st.columns(4)
    trail = e.number_input("Trail ATR ×", 1.0, 6.0, 3.0, 0.5)
    hold = f.number_input("Max hold (days)", 5, 250, 60)
    cost = g.number_input("Cost/side % (STT+brokerage+slippage)", 0.0, 1.0, 0.2, 0.05)
    use_reg = h_.checkbox("Nifty regime filter", True)
    bt_n = st.slider("Kitne stocks (list ke top N) - zyada = slow", 20, len(symbols), min(100, len(symbols)), 10)

    if st.button("▶️ Run backtest", type="primary"):
        period = BT_PERIOD[years]
        nifty_bt = fetch_index(period)
        prices = fetch_all(symbols[:bt_n], period, "History download")
        cfg = BTConfig(years=years, capital=capital, risk_pct=risk_pct, max_pos=int(max_pos),
                       max_pos_pct=max_pos_pct, min_score=bt_score, exit_mode=exit_mode, trail_mult=trail,
                       max_hold=int(hold), cost_pct=cost, use_regime=use_reg)
        with st.spinner("Backtest chal raha hai..."):
            st.session_state["bt"] = run_portfolio(prices, nifty_bt, p, cfg)

    out = st.session_state.get("bt")
    if out is not None:
        met, tr = out["metrics"], out["trades"]
        cols = st.columns(5)
        for i, (k, v) in enumerate(met.items()):
            cols[i % 5].metric(k, v)
        st.subheader(f"Equity curve (₹{capital:,.0f} se start)")
        st.line_chart(out["equity"])
        if tr.empty:
            st.warning("Is setting par koi trade nahi bana. Min score kam karke dekho.")
        else:
            g1, g2 = st.columns(2)
            g1.write("**Score band ke hisaab se**")
            band = tr.assign(Band=tr["Score"].apply(lambda s: "90+" if s >= 90 else "80-89" if s >= 80 else "70-79" if s >= 70 else "<70"))
            g1.dataframe(band.groupby("Band").agg(Trades=("R", "count"), AvgR=("R", "mean"),
                                                 WinRate=("PnL", lambda s: round((s > 0).mean() * 100, 1))).round(2))
            g2.write("**Exit reason**")
            g2.dataframe(tr["Exit reason"].value_counts())
            st.dataframe(tr, use_container_width=True, hide_index=True)
            st.download_button("⬇️ Trades CSV", tr.to_csv(index=False), "backtest_trades.csv", "text/csv")
        st.caption(f"Abhi open positions: {out['open_positions']}. Survivorship bias: aaj ki Nifty 500 list use hoti hai, "
                   "isliye result thoda zyada achha dikh sakta hai. Past performance future ki guarantee nahi.")

# ---------------- Rules ----------------
with tab_about:
    st.markdown(f"""
**Hard filters (pehle):** price ≥ ₹{p.min_price:g}, avg traded value ≥ ₹{p.min_value_cr:g} Cr/day,
{'Close > EMA200, ' if p.require_above_200 else ''}RSI < {p.rsi_max:g}, Close EMA20 se {p.max_ext_pct:g}% se zyada door nahi.

**Score (0-100):**
- Trend 25: Close>EMA200 (10), EMA50>EMA200 (5), EMA20>EMA50 (5), ADX>{p.adx_min:g} (5)
- Momentum 20: RSI {p.rsi_lo:g}-{p.rsi_hi:g} (10), MACD bullish aur badhta hua (10)
- Strength 25: 6 mahine me Nifty se behtar (15), 52-week high ke {p.near_high_pct:g}% ke andar (10)
- Trigger 30: {p.breakout_days}-day breakout (15) + volume {p.vol_mult}× (15), **ya** EMA20 pullback bounce (22)

**BUY** ≥ {p.buy_score}, **WATCH** ≥ {p.watch_score}. **StopLoss** = Entry − {p.atr_mult}×ATR, **Target** = {p.rr}×risk.
**Qty** = (capital × risk%) ÷ (Entry − StopLoss), position size cap ke saath.

⚠️ Educational tool hai, investment advice nahi. Thresholds default hain, pehle backtest chalao phir apne hisaab se tune karo.
""")
