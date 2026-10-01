"""Nifty 500 universe (sector ke saath) + yfinance downloads."""
import io
import os

import pandas as pd
import requests
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_CSV = os.path.join(HERE, "..", "data", "nifty500.csv")
NSE_URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
]
FALLBACK = (
    "RELIANCE TCS HDFCBANK ICICIBANK INFY SBIN BHARTIARTL ITC LT HINDUNILVR AXISBANK KOTAKBANK "
    "BAJFINANCE MARUTI SUNPHARMA TITAN ASIANPAINT ULTRACEMCO NTPC POWERGRID ONGC TATASTEEL "
    "M&M TATAMOTORS ADANIENT ADANIPORTS COALINDIA JSWSTEEL HCLTECH WIPRO TECHM NESTLEIND "
    "BAJAJ-AUTO EICHERMOT HEROMOTOCO DRREDDY CIPLA DIVISLAB APOLLOHOSP HAL BEL SIEMENS "
    "ABB HAVELLS POLYCAB DIXON TRENT ZOMATO INDIGO IRCTC PFC RECLTD BHEL SAIL NMDC "
    "ABDL CARBORUNIV CASTROLIND LALPATHLAB ENGINERSIN GESHIP HBLENGINE HFCL KIRLOSENG "
    "LEMONTREE SYRMA TEGA WHIRLPOOL WELSPUNLIV SCHNEIDER SUNTV"
).split()


def _parse(df):
    df["Symbol"] = df["Symbol"].astype(str).str.strip()
    sec = dict(zip(df["Symbol"], df["Industry"])) if "Industry" in df.columns else {}
    return df["Symbol"].tolist(), sec


def load_universe():
    """(symbols, source, {symbol: sector})"""
    for url in NSE_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            if len(df) > 400:
                os.makedirs(os.path.dirname(LOCAL_CSV), exist_ok=True)
                df.to_csv(LOCAL_CSV, index=False)
                syms, sec = _parse(df)
                return syms, "NSE (live list)", sec
        except Exception:
            continue
    if os.path.exists(LOCAL_CSV):
        try:
            s, sec = _parse(pd.read_csv(LOCAL_CSV))
            return s, "local data/nifty500.csv", sec
        except Exception:
            pass
    return FALLBACK, "built-in fallback (chhoti list) - data/nifty500.csv add karo", {}


def _clean(d):
    d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)
    return d


def download_prices(symbols, period="2y", interval="1d") -> dict:
    tick = [s + ".NS" for s in symbols]
    raw = yf.download(tick, period=period, interval=interval, group_by="ticker",
                      auto_adjust=True, progress=False, threads=True)
    out = {}
    if raw is None or raw.empty:
        return out
    for s, t in zip(symbols, tick):
        try:
            d = _clean(raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw)
            if len(d) >= 60:
                out[s] = d
        except KeyError:
            continue
    return out


def download_index(period="2y"):
    """Nifty 50 close series (^NSEI) ya None."""
    try:
        raw = yf.download("^NSEI", period=period, interval="1d", auto_adjust=True, progress=False)
        c = raw["Close"]
        c = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
        c = c.dropna()
        if getattr(c.index, "tz", None) is not None:
            c.index = c.index.tz_localize(None)
        return c if len(c) > 60 else None
    except Exception:
        return None
