"""CLI scan (GitHub Actions / local): python run_scan.py
Optional Telegram alert: env TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID set karo."""
import datetime as dt
import os

import requests

from scanner.data import download_index, download_prices, load_universe
from scanner.indicators import Params, regime_series, scan_all


def telegram(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": text[:4000]}, timeout=20)


if __name__ == "__main__":
    p = Params()
    syms, src, sectors = load_universe()
    print(f"{len(syms)} symbols ({src})")
    nifty = download_index("2y")
    reg = regime_series(nifty, p)
    regime_ok = True if reg is None else bool(reg.iloc[-1])
    prices = {}
    for i in range(0, len(syms), 50):
        prices.update(download_prices(syms[i:i + 50], period="2y"))
    res = scan_all(prices, p, nifty, sectors, regime_ok=regime_ok)
    res.insert(0, "ScanTime", dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    res.to_csv("results/latest_scan.csv", index=False)
    buys = res[res["Signal"] == "BUY"].head(10) if not res.empty else res
    msg = f"Nifty regime: {'HEALTHY' if regime_ok else 'WEAK'}\n" + (
        "\n".join(f"{r.Symbol} [{r.Score}] {r.Setup} E {r.Entry} SL {r.StopLoss} T {r.Target}"
                  for r in buys.itertuples()) or "Aaj koi BUY signal nahi")
    print(msg)
    telegram(msg)
