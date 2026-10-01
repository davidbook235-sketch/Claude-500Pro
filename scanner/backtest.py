"""Portfolio-level backtest (real equity curve, position limits, Nifty se compare).

Rules:
- Signal candle ke close par score >= min_score  ->  agle din OPEN par entry (score ke order me).
- Market regime weak ho (Nifty < EMA) to naye entry nahi (optional).
- Position size = risk% of equity / (ATR stop distance), max_pos_pct se capped.
- Exit: STOP (gap-aware), TARGET (fixed R:R) ya TRAILING (ATR chandelier), ya TIME.
- Stop aur target same candle me ho to STOP pehle maana jata hai (conservative).
- Cost per side (brokerage + STT + slippage) har buy/sell par.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import MIN_BARS, Params, add_indicators, regime_series


@dataclass
class BTConfig:
    years: int = 3
    capital: float = 500000.0
    risk_pct: float = 1.0
    max_pos: int = 8
    max_pos_pct: float = 20.0
    min_score: int = 70
    exit_mode: str = "Trailing"      # "Trailing" ya "Target"
    trail_mult: float = 3.0
    max_hold: int = 60
    cost_pct: float = 0.2
    use_regime: bool = True


def run_portfolio(prices: dict, nifty, p: Params, cfg: BTConfig):
    ind = {s: add_indicators(df, p, nifty) for s, df in prices.items() if len(df) >= MIN_BARS}
    if not ind:
        return None
    syms = list(ind)
    dates = pd.DatetimeIndex(sorted(set().union(*[d.index for d in ind.values()])))

    def mat(col):
        return np.column_stack([ind[s][col].reindex(dates).values.astype(float) for s in syms])

    O, H, L, C, A = mat("Open"), mat("High"), mat("Low"), mat("Close"), mat("atr")
    SIG = np.nan_to_num(mat("sig"))
    reg = np.ones(len(dates), bool)
    rs = regime_series(nifty, p) if cfg.use_regime else None
    if rs is not None:
        reg = rs.reindex(dates).ffill().fillna(False).values.astype(bool)

    T = len(dates)
    t0 = max(1, int(dates.searchsorted(dates[-1] - pd.DateOffset(years=cfg.years))))
    cost = cfg.cost_pct / 100
    cash, pos, trades = cfg.capital, {}, []
    lastC = np.nan_to_num(C[0])
    eq, inv = [], []

    def close_pos(i, px, why, t):
        nonlocal cash
        q = pos.pop(i)
        cash += q["qty"] * px * (1 - cost)
        pnl = q["qty"] * (px * (1 - cost) - q["entry"] * (1 + cost))
        trades.append({
            "Symbol": syms[i], "Score": int(q["score"]), "EntryDate": q["date"], "ExitDate": dates[t],
            "Entry": round(q["entry"], 2), "Exit": round(px, 2), "Qty": q["qty"], "Exit reason": why,
            "Days": q["days"], "Return%": round((px / q["entry"] - 1) * 100 - 2 * cfg.cost_pct, 2),
            "R": round((px - q["entry"]) / q["risk"], 2), "PnL": round(pnl),
        })

    for t in range(1, T):
        m = ~np.isnan(C[t])
        lastC[m] = C[t][m]
        if t < t0:
            continue
        # ---- exits ----
        for i in list(pos):
            if np.isnan(H[t, i]):
                continue
            q = pos[i]
            q["days"] += 1
            o, h, l, c = O[t, i], H[t, i], L[t, i], C[t, i]
            if l <= q["stop"]:
                close_pos(i, min(q["stop"], o), "STOP", t)
            elif cfg.exit_mode == "Target" and h >= q["target"]:
                close_pos(i, max(q["target"], o), "TARGET", t)
            elif q["days"] >= cfg.max_hold:
                close_pos(i, c, "TIME", t)
            elif cfg.exit_mode == "Trailing":
                q["high"] = max(q["high"], h)
                if not np.isnan(A[t, i]):
                    q["stop"] = max(q["stop"], q["high"] - cfg.trail_mult * A[t, i])
        # ---- entries (signal = kal ka close) ----
        if len(pos) < cfg.max_pos and reg[t - 1]:
            ok = (SIG[t - 1] >= cfg.min_score) & ~np.isnan(O[t]) & ~np.isnan(A[t - 1])
            cand = sorted((i for i in np.where(ok)[0] if i not in pos), key=lambda i: -SIG[t - 1, i])
            equity_now = cash + sum(q["qty"] * lastC[i] for i, q in pos.items())
            for i in cand:
                if len(pos) >= cfg.max_pos:
                    break
                e, risk = O[t, i], p.atr_mult * A[t - 1, i]
                if risk <= 0 or e - risk <= 0:
                    continue
                qty = int(min(equity_now * cfg.risk_pct / 100 / risk,
                              equity_now * cfg.max_pos_pct / 100 / e, cash / (e * (1 + cost))))
                if qty < 1:
                    continue
                cash -= qty * e * (1 + cost)
                pos[i] = {"entry": e, "stop": e - risk, "target": e + p.rr * risk, "risk": risk,
                          "qty": qty, "days": 0, "high": e, "date": dates[t], "score": SIG[t - 1, i]}
                if L[t, i] <= pos[i]["stop"]:           # entry din hi stop hit
                    close_pos(i, pos[i]["stop"], "STOP", t)
        val = sum(q["qty"] * lastC[i] for i, q in pos.items())
        eq.append(cash + val)
        inv.append(val / (cash + val))

    idx = dates[t0:]
    eqs = pd.Series(eq, index=idx)
    open_n = len(pos)
    tr = pd.DataFrame(trades)
    res = {"trades": tr, "open_positions": open_n}
    ret = eqs.pct_change().dropna()
    yrs = max((idx[-1] - idx[0]).days / 365.25, 1e-9)
    dd = (eqs / eqs.cummax() - 1).min()
    m = {
        "Total return %": round((eqs.iloc[-1] / cfg.capital - 1) * 100, 1),
        "CAGR %": round(((eqs.iloc[-1] / cfg.capital) ** (1 / yrs) - 1) * 100, 1),
        "Max drawdown %": round(dd * 100, 1),
        "Sharpe": round(ret.mean() / ret.std() * np.sqrt(252), 2) if ret.std() > 0 else 0.0,
        "Avg exposure %": round(float(np.mean(inv)) * 100, 0),
    }
    if not tr.empty:
        w, l_ = tr[tr["PnL"] > 0], tr[tr["PnL"] <= 0]
        m.update({
            "Trades": len(tr), "Win rate %": round(len(w) / len(tr) * 100, 1),
            "Avg R": round(tr["R"].mean(), 2),
            "Profit factor": round(w["PnL"].sum() / abs(l_["PnL"].sum()), 2) if l_["PnL"].sum() != 0 else float("inf"),
            "Avg win %": round(w["Return%"].mean(), 2) if len(w) else 0.0,
            "Avg loss %": round(l_["Return%"].mean(), 2) if len(l_) else 0.0,
            "Avg hold days": round(tr["Days"].mean(), 1),
        })
    curve = pd.DataFrame({"Strategy": eqs})
    if nifty is not None:
        b = nifty.reindex(dates).ffill().loc[idx]
        curve["Nifty 50 (buy&hold)"] = b / b.iloc[0] * cfg.capital
        m["Nifty return %"] = round((b.iloc[-1] / b.iloc[0] - 1) * 100, 1)
        m["Nifty max DD %"] = round(((b / b.cummax()) - 1).min() * 100, 1)
    res.update(metrics=m, equity=curve)
    return res
