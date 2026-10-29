import os, time, logging, requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dd-bhai")
TD_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
INTERVAL = os.getenv("CANDLE_INTERVAL", "5min")
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "30"))  # Starter threshold for implemented subset only
RISK_PCT = float(os.getenv("PAPER_RISK_PCT", "0.5"))
http = requests.Session()
last_bar = {}

FX_METALS = [("XAU/USD", "Gold"), ("EUR/USD", "Forex"), ("GBP/USD", "Forex"), ("USD/JPY", "Forex")]
CRYPTOS = [("BTCUSDT", "Crypto"), ("ETHUSDT", "Crypto")]

def send_telegram(text):
    if not TG_TOKEN or not TG_CHAT:
        log.warning("Telegram credentials missing; signal preview:\n%s", text)
        return
    r = http.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  json={"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": True}, timeout=15)
    r.raise_for_status()
    if not r.json().get("ok"):
        log.error("Telegram API error: %s", r.text)

def candles_twelvedata(symbol):
    if not TD_KEY:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY in .env")
    r = http.get("https://api.twelvedata.com/time_series",
                 params={"symbol": symbol, "interval": INTERVAL, "outputsize": 400,
                         "timezone": "UTC", "apikey": TD_KEY}, timeout=25)
    r.raise_for_status()
    j = r.json()
    if "values" not in j:
        raise RuntimeError(j.get("message", str(j)))
    d = pd.DataFrame(j["values"]).rename(columns={"datetime": "time"})
    for c in ["open", "high", "low", "close", "volume"]:
        if c in d: d[c] = pd.to_numeric(d[c], errors="coerce")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    return d.dropna(subset=["time","open","high","low","close"]).sort_values("time").reset_index(drop=True)

def candles_binance(symbol):
    itv = {"1min":"1m","5min":"5m","15min":"15m","30min":"30m","1h":"1h","4h":"4h","1day":"1d"}.get(INTERVAL, "5m")
    r = http.get("https://data-api.binance.vision/api/v3/klines",
                 params={"symbol":symbol,"interval":itv,"limit":400}, timeout=20)
    r.raise_for_status()
    d = pd.DataFrame(r.json(), columns=["open_ms","open","high","low","close","volume","close_ms","qv","n","tb","tq","x"])
    for c in ["open","high","low","close","volume"]: d[c] = pd.to_numeric(d[c], errors="coerce")
    d["time"] = pd.to_datetime(d["open_ms"], unit="ms", utc=True)
    # Exclude candle still forming
    d = d[d["close_ms"] < int(datetime.now(timezone.utc).timestamp()*1000)]
    return d[["time","open","high","low","close","volume"]].dropna().reset_index(drop=True)

def indicators(d):
    d=d.copy()
    d["ema13"]=d.close.ewm(span=13,adjust=False).mean()
    d["ema34"]=d.close.ewm(span=34,adjust=False).mean()
    d["ema200"]=d.close.ewm(span=200,adjust=False).mean()
    d["hh20"]=d.high.shift(1).rolling(20).max()
    d["ll20"]=d.low.shift(1).rolling(20).min()
    delta=d.close.diff()
    gain=delta.clip(lower=0).rolling(14).mean()
    loss=(-delta.clip(upper=0)).rolling(14).mean()
    d["rsi"]=100-100/(1+gain/loss.replace(0,np.nan))
    tr=pd.concat([d.high-d.low,(d.high-d.close.shift()).abs(),(d.low-d.close.shift()).abs()],axis=1).max(axis=1)
    d["atr"]=tr.rolling(14).mean()
    d["roc24"]=d.close.pct_change(24)
    return d

def evaluate(d):
    # Starter subset only. Full supplied Master Strategy Library is NOT yet implemented.
    if len(d)<220: return None
    r=d.iloc[-1]
    if any(pd.isna(r[k]) for k in ["ema13","ema34","ema200","hh20","ll20","rsi","atr","roc24"]) or r.atr<=0: return None
    long_score=short_score=0
    lr=[]; sr=[]
    if r.close>r.ema200: long_score+=16; lr.append("price above EMA200")
    elif r.close<r.ema200: short_score+=16; sr.append("price below EMA200")
    if r.ema13>r.ema34: long_score+=6; lr.append("EMA13 > EMA34")
    elif r.ema13<r.ema34: short_score+=6; sr.append("EMA13 < EMA34")
    if r.close>r.hh20: long_score+=14; lr.append("20-bar breakout")
    elif r.close<r.ll20: short_score+=14; sr.append("20-bar breakdown")
    if r.roc24>0: long_score+=6; lr.append("ROC positive")
    elif r.roc24<0: short_score+=6; sr.append("ROC negative")
    if 46<=r.rsi<=72: long_score+=12; lr.append("RSI continuation")
    if 28<=r.rsi<=54: short_score+=12; sr.append("RSI continuation")
    direction=1 if long_score>=MIN_SCORE and long_score>short_score else -1 if short_score>=MIN_SCORE and short_score>long_score else 0
    return {"direction":direction,"score":long_score if direction==1 else short_score if direction==-1 else max(long_score,short_score),
            "long":long_score,"short":short_score,"reasons":lr if direction==1 else sr,"price":float(r.close),
            "atr":float(r.atr),"rsi":float(r.rsi),"time":str(r.time)}

def scan(symbol, asset, fetch):
    try:
        d=indicators(fetch(symbol))
        res=evaluate(d)
        if not res: return
        if last_bar.get(symbol)==res["time"]: return
        last_bar[symbol]=res["time"]
        log.info("%s %s score=%s",symbol,res["direction"],res["score"])
        if res["direction"]==0: return
        side="BUY" if res["direction"]==1 else "SELL"
        sl_mult,tp1_mult,tp2_mult=(1.5,1.0,2.5) if asset=="Crypto" else (1.0,0.8,1.8)
        direction=res["direction"]; p=res["price"]; atr=res["atr"]
        sl=p-direction*sl_mult*atr; tp1=p+direction*tp1_mult*atr; tp2=p+direction*tp2_mult*atr
        msg=(f"DD BHAI • PAPER SIGNAL\n{asset}: {symbol}\nSide: {side}\nTimeframe: {INTERVAL}\n"
             f"Closed candle UTC: {res['time']}\nReference entry: {p:.6f}\nSL: {sl:.6f}\n"
             f"TP1: {tp1:.6f}\nTP2: {tp2:.6f}\nRule score: {res['score']} (not win probability)\n"
             f"RSI: {res['rsi']:.1f}\nRules: {', '.join(res['reasons'])}\n"
             f"Paper risk setting: {RISK_PCT:.2f}%\nNo live orders; verify broker prices and costs.")
        send_telegram(msg)
    except Exception as e:
        log.warning("%s scan failed: %s", symbol, e)

def main():
    send_telegram("DD Bhai Telegram Alert Bot started. PAPER/ALERT ONLY; no live orders.")
    while True:
        started=time.time()
        for sym,asset in FX_METALS: scan(sym,asset,candles_twelvedata)
        for sym,asset in CRYPTOS: scan(sym,asset,candles_binance)
        time.sleep(max(5,SCAN_SECONDS-(time.time()-started)))

if __name__=="__main__": main()
