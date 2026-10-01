"""Pro scoring engine (0-100) for Indian equities.

Hard filters (liquidity, price, trend, not overextended) pehle lagte hain, phir 0-100 score:
  Trend 25  : Close>EMA200 (10), EMA50>EMA200 (5), EMA20>EMA50 (5), ADX>min (5)
  Momentum 20: RSI band (10), MACD bullish & rising (10)
  Strength 25: Nifty se outperform (15), 52w high ke paas (10)
  Trigger 30 : breakout (15) + volume spike (15)  YA  EMA20 pullback bounce (22)
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Params:
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200
    rsi_period: int = 14
    rsi_lo: float = 55.0
    rsi_hi: float = 75.0
    rsi_max: float = 80.0          # isse upar overbought -> reject
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    breakout_days: int = 20
    vol_days: int = 20
    vol_mult: float = 1.5
    adx_min: float = 20.0
    rs_days: int = 126             # ~6 mahine relative strength
    near_high_pct: float = 15.0    # 52w high ke itne % ke andar
    min_price: float = 50.0
    min_value_cr: float = 5.0      # avg daily traded value (Rs crore)
    max_ext_pct: float = 12.0      # EMA20 se zyada door = chase mat karo
    require_above_200: bool = True
    regime_ema: int = 50           # Nifty > EMA(regime_ema) = market healthy
    atr_period: int = 14
    atr_mult: float = 2.0
    rr: float = 2.5
    buy_score: int = 70
    watch_score: int = 55


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    ru = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rd = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + ru / rd.replace(0, np.nan))
    out[(rd == 0) & ru.notna()] = 100.0
    return out


def _tr(df):
    pc = df["Close"].shift(1)
    return pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)


def atr(df, n=14):
    return _tr(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df, n=14):
    up, dn = df["High"].diff(), -df["Low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / a
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def regime_series(nifty, p):
    """True = Nifty apni EMA ke upar (market healthy)."""
    if nifty is None or len(nifty) < p.regime_ema:
        return None
    return (nifty > ema(nifty, p.regime_ema)).astype(bool)


COND_LABELS = {
    "c_e200": "Close > EMA200",
    "c_e50": "EMA50 > EMA200",
    "c_ema": "EMA20 > EMA50",
    "c_adx": "ADX strong",
    "c_rsi": "RSI 55-75",
    "c_macd": "MACD bullish & rising",
    "c_rs": "Outperforming Nifty",
    "c_near": "Near 52w high",
    "c_brk": "20d breakout",
    "c_vol": "Volume spike",
    "c_pull": "EMA20 pullback bounce",
}


def add_indicators(df, p: Params, nifty=None):
    d = df.copy()
    c = d["Close"]
    d["ema_f"], d["ema_m"], d["ema_l"] = ema(c, p.ema_fast), ema(c, p.ema_mid), ema(c, p.ema_slow)
    d["rsi"] = rsi(c, p.rsi_period)
    d["macd"] = ema(c, p.macd_fast) - ema(c, p.macd_slow)
    d["macd_sig"] = ema(d["macd"], p.macd_signal)
    d["macd_hist"] = d["macd"] - d["macd_sig"]
    d["atr"] = atr(d, p.atr_period)
    d["adx"] = adx(d, p.atr_period)
    d["hh"] = d["High"].shift(1).rolling(p.breakout_days).max()
    d["vol_ratio"] = d["Volume"] / d["Volume"].shift(1).rolling(p.vol_days).mean()
    d["value_cr"] = (c * d["Volume"]).rolling(20).mean() / 1e7
    d["hi52"] = d["High"].rolling(252, min_periods=120).max()
    d["from_high"] = (c / d["hi52"] - 1) * 100
    d["ret_rs"] = c / c.shift(p.rs_days) - 1
    if nifty is not None:
        n = nifty.reindex(d.index).ffill()
        d["rs"] = d["ret_rs"] - (n / n.shift(p.rs_days) - 1)
    else:
        d["rs"] = np.nan

    d["c_e200"] = c > d["ema_l"]
    d["c_e50"] = d["ema_m"] > d["ema_l"]
    d["c_ema"] = d["ema_f"] > d["ema_m"]
    d["c_adx"] = d["adx"] > p.adx_min
    d["c_rsi"] = (d["rsi"] > p.rsi_lo) & (d["rsi"] <= p.rsi_hi)
    d["c_macd"] = (d["macd_hist"] > 0) & (d["macd_hist"] > d["macd_hist"].shift(1))
    d["c_rs"] = d["rs"] > 0
    d["c_near"] = d["from_high"] >= -p.near_high_pct
    d["c_brk"] = c > d["hh"]
    d["c_vol"] = d["vol_ratio"] > p.vol_mult
    trend_ok = (c > d["ema_m"]) & (d["ema_m"] > d["ema_l"])
    d["c_pull"] = trend_ok & (d["Low"] <= d["ema_f"] * 1.015) & (c > d["ema_f"]) & d["rsi"].between(40, 62)
    conds = list(COND_LABELS)
    d[conds] = d[conds].fillna(False).astype(bool)

    trend = 10 * d["c_e200"] + 5 * d["c_e50"] + 5 * d["c_ema"] + 5 * d["c_adx"]
    mom = 10 * d["c_rsi"] + 10 * d["c_macd"]
    strg = 15 * d["c_rs"] + 10 * d["c_near"]
    trig = np.maximum(15 * d["c_brk"] + 15 * d["c_vol"], 22 * d["c_pull"])
    d["score"] = (trend + mom + strg + trig).astype(int)

    ok = (c >= p.min_price) & (d["value_cr"] >= p.min_value_cr) & (d["rsi"] < p.rsi_max) \
        & ((c / d["ema_f"] - 1) * 100 <= p.max_ext_pct)
    if p.require_above_200:
        ok &= d["c_e200"]
    d["ok"] = ok.fillna(False)
    d["sig"] = d["score"].where(d["ok"], 0)
    d["setup"] = np.select(
        [d["c_brk"] & d["c_vol"], d["c_pull"], d["c_brk"]],
        ["Breakout", "Pullback", "Breakout (low vol)"], default="Momentum")
    return d


MIN_BARS = 220


def scan_all(prices, p: Params, nifty=None, sectors=None, capital=500000.0, risk_pct=1.0,
             max_pos_pct=20.0, regime_ok=True, block_weak=True, min_rs_rank=0):
    rows = []
    for s, df in prices.items():
        if df is None or len(df) < MIN_BARS:
            continue
        r = add_indicators(df, p, nifty).iloc[-1]
        if pd.isna(r["atr"]):
            continue
        rows.append({"Symbol": s, "_r": r})
    if not rows:
        return pd.DataFrame()
    rs_rank = pd.Series({x["Symbol"]: x["_r"]["ret_rs"] for x in rows}).rank(pct=True) * 100
    labels, out = COND_LABELS, []
    for x in rows:
        r, s = x["_r"], x["Symbol"]
        if r["sig"] < p.watch_score or rs_rank[s] < min_rs_rank:
            continue
        entry, risk = float(r["Close"]), p.atr_mult * float(r["atr"])
        sl = entry - risk
        qty = int(max(0, min(capital * risk_pct / 100 / risk, capital * max_pos_pct / 100 / entry)))
        buy = r["sig"] >= p.buy_score and (regime_ok or not block_weak)
        out.append({
            "Symbol": s, "Sector": (sectors or {}).get(s, ""),
            "Signal": "BUY" if buy else "WATCH", "Score": int(r["sig"]), "Setup": r["setup"],
            "Entry": round(entry, 2), "StopLoss": round(sl, 2), "Target": round(entry + p.rr * risk, 2),
            "Risk%": round(risk / entry * 100, 2), "Qty": qty, "Position": round(qty * entry),
            "RSI": round(float(r["rsi"]), 1), "ADX": round(float(r["adx"]), 1),
            "VolX": round(float(r["vol_ratio"]), 2) if pd.notna(r["vol_ratio"]) else None,
            "RS vs Nifty %": round(float(r["rs"]) * 100, 1) if pd.notna(r["rs"]) else None,
            "RS Rank": round(float(rs_rank[s])), "From 52wH %": round(float(r["from_high"]), 1),
            "Reasons": ", ".join(v for k, v in labels.items() if r[k]),
        })
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values(["Score", "RS Rank"], ascending=False).reset_index(drop=True)
