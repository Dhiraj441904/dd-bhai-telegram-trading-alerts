# DD Bhai Telegram Alert Bot — Starter V1

## Data sources
- Gold/Forex: Twelve Data (`XAU/USD`, `EUR/USD`, `GBP/USD`, `USD/JPY`)
- Crypto: Binance public market-data API (`BTCUSDT`, `ETHUSDT`)
- Alerts: Telegram Bot API

Check your Twelve Data subscription before relying on real-time Gold data; symbol and interval access depends on plan.

## Setup
1. Create a bot with Telegram `@BotFather` and get the bot token.
2. Create a Twelve Data account and copy its API key.
3. Copy `.env.example` to `.env` and fill in your keys and chat ID.
4. Install Python 3.11+ and run:
   `pip install -r requirements.txt`
   `python app.py`
5. Keep it running on a reliable VPS/server for continuous scanning.

## Important limitations
- This starter implements only a small subset of your strategy library: EMA200 bias, EMA13/34, 20-bar breakout, ROC sign, and RSI continuation bands.
- It does NOT yet implement the full Master Strategy Library, complete 148-point scoring, ADX, SuperTrend, divergence, all price-action rules, spread/session/news filters, full risk management, or historical walk-forward backtesting.
- Your listed weights sum to 148, not 132. Current `MIN_SCORE=30` is a temporary threshold for the subset and must be recalibrated after full scoring is implemented.
- This bot sends reference alerts only. It does not execute broker orders and does not accurately model Vantage spreads, slippage, swaps, contract size or margin.
- Never upload `.env` or API tokens to GitHub.
- No win rate or return is guaranteed. Paper-test first.
