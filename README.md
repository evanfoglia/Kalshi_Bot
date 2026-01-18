# Kalshi BTC Momentum Bot 🚀

## Project Goal
This project is an automated trading bot designed to profit from **Bitcoin (BTC)** price movements on **Kalshi's 15-minute prediction markets**.
Instead of predicting the exact price, it predicts **volatility and mean reversion**:
*   If BTC crashes fast → Bet it will **bounce back up** (Mean Reversion).
*   If BTC goes parabolic → Short the top.

> [!NOTE]
> **Simulation Mode Active**
> This bot currently operates in a **Paper Trading Mode**. It starts with a virtual balance of **$1,000** and tracks theoretical performance. It **does not** place real bets or use real funds on Kalshi yet.

## 🧠 Core Strategy ("Optimized Momentum")
The bot uses a **probabilistic approach** based on 30-day historical data (40,000+ samples). It uses **Backtested Heuristics** targeting >70% win-rate setups.

### Active Triggers (Optimized)
The bot currently trades these high-probability signals:

| Signal | Logic | Condition | Win Rate | Frequency |
| :--- | :--- | :--- | :--- | :--- |
| **Golden Signal** | Reversion | RSI > **80** + Red Candle 5m | **~80.6%** | Low (Sniper) |
| **Buy the Dip** | Reversion | Price drops **> 0.3%** in 15 mins | **~69.8%** | High (Volume) |
| **Turbo Short** | Reversion | RSI > **70** + Red Candle 5m | **~72.5%** | Medium |

**Auto-Calibration:**
Every time the bot starts, it downloads the last **30 days** of BTC data. It then uses the most recent **14 days** to *re-calculate* the win rates. This ensures the bot adapts to the latest market regime (e.g., stopping a strategy if it hasn't worked in the last 2 weeks).

---

## 📂 File Structure & Architecture

### 1. The Controller (`watchdog.py`)
*   **The Manager:** You run this file. It manages the bot process.
*   **Features:**
    *   **Crash Recovery:** Automatically restarts the bot if it crashes.
    *   **Freeze Detection:** Monitors log files. If the bot stops writing logs for 5 minutes (frozen WebSocket), the watchdog kills and restarts it.

### 2. The Brain (`src/`)
*   **`bot_momentum.py` (THE NERVE CENTER)**
    *   **What it does:** Connects to Binance (for real-time price) and Kalshi (for trading). It runs an infinite loop: `Get Price -> Check Signals -> Place Trade`.
    *   **Features:** Auto-updates data, manages risk (Kelly Criterion), and logs everything.

*   **`strategy.py` (THE SINGLE SOURCE OF TRUTH)**
    *   **What it does:** Contains the **exact trading rules** used by both the live bot and the backtester. If you want to change the strategy, you edit *only this file*.
    *   **Current Active Signals (Ordered by Priority):**
        | Signal | Condition | Win Rate |
        |---|---|---|
        | **Golden Signal** | RSI > 80 + 5m Red Candle | **80.6%** |
        | **High Confidence** | RSI > 75 + 5m Red Candle | **77.7%** |
        | **Turbo Mode** | RSI > 70 + 5m Red Candle | **71.9%** |
        | **Mean Reversion** | 15m Price Drop > 0.3% | **69.6%** |
    *   **Why this matters:** The bot and backtest import the same function, so they are *guaranteed* to match. No more "works in backtest, fails live" surprises.

*   **`backtest_momentum.py` (THE SIMULATOR)**
    *   **What it does:** Runs the strategy on historical data to tell you "What *would* have happened?".
    *   **Usage:** running `python3 src/backtest_momentum.py --days 30` tells you the bot's expected win rate.
    *   **Key:** It imports `strategy.py`, so the results are accurate.

*   **`features.py` (THE MATH)**
    *   **What it does:** Calculates the indicators (RSI, Moving Averages, Percentage Returns).
    *   **Key:** Uses "Wilder's Smoothing" for RSI, ensuring our numbers match TradingView/Binance exactly.

*   **`api.py` (THE CONNECTORS)**
    *   **What it does:** Handles the nitty-gritty of talking to the outside world.
    *   **`BinanceWSServer`:** A background thread that listens to a massive stream of BTC trades from Binance US/Global.
    *   **`KalshiAPI`:** Wrapper for Kalshi's trade API (finding markets, placing orders).

*   **`collector.py` (THE ARCHIVIST)**
    *   **What it does:** Downloads historical 1-minute candles from Binance API and saves them to `data/btc_1min_data.csv`.

### 3. The Logs (`logs/`)
*   **`momentum_events.log`**: The diary. "I saw RSI 75, but didn't trade because..."
*   **`momentum_trades.csv`**: The ledger. "Bought YES at $0.24, Sold at $0.00".

### 4. The Data (`data/`)
*   **`btc_1min_data.csv`**: The brain's memory. Contains ~43,000 rows of minute-by-minute BTC price history used for calibration.

---

## ⚡ How to Run

### 1. Start the Bot (Recommended)
Run the Watchdog, which handles the bot:

**Mac/Linux (Prevents Sleep):**
```bash
caffeinate -i python3 watchdog.py
```

**Windows:**
```powershell
python watchdog.py
```
*> **Note for Windows:** To prevent your PC from sleeping (stopping the bot), go to **Settings > System > Power & sleep** and set Sleep to "Never", or use [Microsoft PowerToys Awake](https://learn.microsoft.com/en-us/windows/powertoys/awake).*

*This is the "Set and Forget" mode.*

### 2. Check Expected Performance
```bash
python3 src/backtest_momentum.py --days 30
```
*See how the strategy performed over the last month.*

---

## ⚙️ Configuration
*   **Time Window:** The bot searches for markets expiring in **2 to 14.5 minutes**.
*   **Bet Sizing:** Variable (Kelly Criterion). Stronger signals (like Golden Signal) = Bigger bets.
*   **Cooldown:** 5 minutes between trades (to prevent over-trading the same signal).
*   **Logging:** Stats are printed to console and saved to logs every 5 minutes.
