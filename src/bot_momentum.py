"""
Simple Momentum Bot for Kalshi KXBTC15M
Uses high win-rate heuristics instead of ML model

Based on backtest results:
- RSI > 80 → Bet NO: 67.5% win rate
- RSI > 75 → Bet NO: 67.3% win rate  
- 15m return < -0.4% → Bet YES: 65.7% win rate
- 15m return > 0.4% → Bet NO: 64.1% win rate

Optimal hours (UTC): 22, 06, 05, 01, 17, 00, 21, 16, 08, 10 (>70% win rate)
"""

import time
import json
import requests
import pandas as pd
import numpy as np
import csv
import os
from datetime import datetime, timezone, timedelta

# Reuse WebSocket from main bot
from api import BinanceWSServer, KalshiAPI
from features import add_technical_indicators
from strategy import get_signal  # <--- SHARED LOGIC

class SimpleMomentumBot:
    def __init__(self):
        # Initialize connections
        self.ws = BinanceWSServer()
        self.ws.start()
        self.kalshi = KalshiAPI()
        
        # State
        self.balance = 1000.0
        self.positions = []
        self.wins = 0
        self.losses = 0
        self.last_trade_time = 0  # Cooldown tracking
        self.TRADE_COOLDOWN_SECONDS = 300  # 5 min between trades
        
        # Session tracking
        self.session_start = time.time()
        self.signals_seen = 0
        self.signals_taken = 0
        self.signals_skipped_cooldown = 0
        self.signals_skipped_price = 0
        self.last_stats_print = 0
        
        # Logging
        self.log_file = "logs/momentum_trades.csv"
        self.event_log = "logs/momentum_events.log"
        os.makedirs("logs", exist_ok=True)
        self._init_log()
        
        # History for indicators
        self.update_data_file()  # <--- NEW: Auto-update data on startup
        self.history_df = self.fetch_initial_history()
        
        # Auto-calibrate win rates from recent data
        self.calibrated_rates = self.calibrate_win_rates()
        
        # State persistence
        self.state_file = "momentum_bot_state.json"
        
    def update_data_file(self):
        """Run collector to get fresh data for calibration"""
        from collector import BinanceDataCollector
        
        # Freshness Check: Skip if file is less than 60 mins old
        file_path = "data/btc_1min_data.csv"
        if os.path.exists(file_path):
            modified_time = os.path.getmtime(file_path)
            age_minutes = (time.time() - modified_time) / 60
            if age_minutes < 60:
                print(f"✅ Data is fresh ({int(age_minutes)}m old). Skipping download.")
                self.state_file = "momentum_bot_state.json"
                self.load_state()
                self.initial_balance = self.balance
                return

        print("🔄 Updating historical data for calibration...")
        try:
            collector = BinanceDataCollector()
            # Fetch last 30 days to be safe
            raw = collector.fetch_historical_data(days=30)
            df = collector.to_dataframe(raw)
            os.makedirs("data", exist_ok=True)
            df.to_csv(file_path)
            print(f"✅ Data updated: {len(df):,} records")
        except Exception as e:
            print(f"⚠️ Data update failed: {e}")
            print("   Using existing data (calibration might be stale)")
        self.state_file = "momentum_bot_state.json"
        self.load_state()
        self.initial_balance = self.balance
    
    def calibrate_win_rates(self, days=14):
        """
        Auto-calibrate expected win rates from recent historical data.
        Returns dict of signal_name -> win_rate
        """
        print(f"📊 Auto-calibrating win rates from last {days} days...")
        
        try:
            # Try to load historical data
            df = pd.read_csv("data/btc_1min_data.csv", index_col='timestamp', parse_dates=True)
            
            # Filter to last N days
            minutes_to_keep = days * 24 * 60
            if len(df) > minutes_to_keep:
                df = df.iloc[-minutes_to_keep:]
            
            df = add_technical_indicators(df).dropna()
            
            # Calculate future outcome (15 min lookahead)
            df['future_close'] = df['close'].shift(-15)
            df['won_yes'] = (df['future_close'] > df['close']).astype(int)
            df['won_no'] = (df['future_close'] <= df['close']).astype(int)
            df = df.dropna()
            
            rates = {}
            
            # RSI > 80 (No Confirmation) - Extreme
            mask = df['rsi_14'] > 80
            if mask.sum() >= 20:
                rates['rsi_80'] = df.loc[mask, 'won_no'].mean()
            else:
                rates['rsi_80'] = 0.676  # Default
            
            # RSI > 70 + DIP → NO (Turbo Mode)
            # Replaced RSI > 75 with RSI > 70 to capture more trades
            mask = (df['rsi_14'] > 70) & (df['return_5m'] < 0)
            if mask.sum() >= 50:
                rates['rsi_70_confirm'] = df.loc[mask, 'won_no'].mean()
            else:
                rates['rsi_70_confirm'] = 0.67  # New default
            
            # REMOVED: RSI > 75 (Subsumed by > 70)
            
            # 15m drop < -0.5% → YES (Loosened from -0.6% for Turbo Volume)
            mask = df['return_15m'] < -0.005
            if mask.sum() >= 20:
                rates['15m_drop'] = df.loc[mask, 'won_yes'].mean()
            else:
                rates['15m_drop'] = 0.708  # Default
            
            # 15m spike > 0.8% → NO (Tightened from 0.4%)
            # Previous strong spike signal was weak. Only fading extreme moves now.
            mask = (df['return_15m'] > 0.008) & (df['return_5m'] < 0)
            if mask.sum() >= 20:
                rates['15m_spike'] = df.loc[mask, 'won_no'].mean()
            else:
                rates['15m_spike'] = 0.60  # Conservative default
            
            print(f"   ✅ Calibrated win rates:")
            for signal, rate in rates.items():
                print(f"      {signal}: {rate:.1%}")
            
            return rates
            
        except Exception as e:
            print(f"   ⚠️ Calibration failed ({e}), using defaults")
            return {
                'rsi_80_confirm': 0.73,
                'rsi_75': 0.673,
                '15m_drop': 0.837,
                '15m_spike': 0.60
            }
        
    def _init_log(self):
        with open(self.log_file, 'a', newline='') as f:
            if f.tell() == 0:
                csv.writer(f).writerow([
                    'timestamp', 'ticker', 'direction', 'signal', 
                    'rsi', 'return_15m', 'price', 'contracts', 'status', 'pnl'
                ])
    
    def save_state(self):
        state = {
            'balance': self.balance,
            'positions': self.positions,
            'wins': self.wins,
            'losses': self.losses
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=4)
    
    def load_state(self):
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                self.balance = state.get('balance', 1000.0)
                self.positions = state.get('positions', [])
                self.wins = state.get('wins', 0)
                self.losses = state.get('losses', 0)
                print(f"🔄 Resumed: ${self.balance:.2f}, {len(self.positions)} open positions")
        except FileNotFoundError:
            print("🆕 Starting fresh with $1000")
    
    def fetch_initial_history(self):
        """Fetch last 100 mins of data to warm up indicators (using Kraken)"""
        print("📥 Warming up historical data from Kraken...")
        url = "https://api.kraken.com/0/public/OHLC"
        resp = requests.get(url, params={"pair": "XBTUSD", "interval": 1})
        data = resp.json()
        
        if data.get('error') and len(data['error']) > 0:
            print(f"⚠️ Kraken API error: {data['error']}")
            # Return empty dataframe with correct structure
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume', 'taker_buy_base'])
        
        # Kraken returns: {result: {XXBTZUSD: [[time, open, high, low, close, vwap, volume, count], ...]}}
        ohlc_data = list(data.get('result', {}).values())[0] if data.get('result') else []
        
        if not ohlc_data or len(ohlc_data) < 2:
            print("⚠️ No OHLC data from Kraken")
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume', 'taker_buy_base'])
        
        # Take last 100 candles (skip the 'last' timestamp at end)
        candles = ohlc_data[-101:-1] if len(ohlc_data) > 100 else ohlc_data[:-1]
        
        df = pd.DataFrame(candles, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        df['taker_buy_base'] = df['volume'] * 0.5  # Estimate (Kraken doesn't provide this)
        df.set_index('timestamp', inplace=True)
        print(f"   Loaded {len(df)} candles")
        return df
    
    def update_history(self):
        """Update history with latest candle"""
        if self.ws.current_candle:
            c = self.ws.current_candle
            if c['is_closed']:
                new_row = pd.Series({
                    'open': c['open'], 'high': c['high'], 'low': c['low'],
                    'close': c['close'], 'vwap': c['close'],  # Use close as vwap estimate
                    'volume': c['volume'], 'count': 1,
                    'taker_buy_base': c['taker_buy_base']
                }, name=c['timestamp'])
                self.history_df = pd.concat([self.history_df, new_row.to_frame().T])
                if len(self.history_df) > 100:
                    self.history_df = self.history_df.iloc[-100:]
    
    def get_current_indicators(self):
        """Calculate current technical indicators"""
        temp_df = self.history_df.copy()
        
        # Add current (incomplete) candle
        if self.ws.current_candle:
            c = self.ws.current_candle
            new_row = {
                'open': c['open'], 'high': c['high'], 'low': c['low'],
                'close': c['close'], 'vwap': c['close'],
                'volume': c['volume'], 'count': 1,
                'taker_buy_base': c['taker_buy_base']
            }
            temp_df.loc[c['timestamp']] = new_row
        
        df = add_technical_indicators(temp_df)
        return df.iloc[-1].to_dict()
    
    # Optimal trading hours (UTC) - these have >70% win rate for RSI strategy
    BEST_HOURS_UTC = {22, 6, 5, 1, 17, 0, 21, 16, 8, 10}
    
    def get_signal(self, indicators):
        """
        Generate trading signal using SHARED logic (src/strategy.py).
        Adds hourly boosts on top of the base signal.
        """
        # Get base signal from shared library
        rates = getattr(self, 'calibrated_rates', {})
        result = get_signal(indicators, rates)
        
        if result:
            direction, signal_name, wr = result
            
            # Contextual Boosts (Bot-specific knowledge)
            current_hour = datetime.now(timezone.utc).hour
            hour_boost = 0.03 if current_hour in self.BEST_HOURS_UTC else 0
            
            return (direction, signal_name, wr + hour_boost)
            
        return None
    
    def calculate_bet_size(self, expected_wr, price):
        """
        Kelly-based position sizing.
        Bet more when expected win rate is higher.
        """
        # Kelly fraction = (p*b - q) / b where b=odds, p=win prob, q=1-p
        # For binary options at price p: b = (1-price)/price
        if price <= 0 or price >= 1:
            return 0
        
        b = (1.0 - price) / price  # Payout odds
        p = expected_wr
        q = 1 - p
        
        kelly = (p * b - q) / b
        
        # Use 1/4 Kelly for safety (less aggressive)
        fraction = max(0, min(kelly * 0.25, 0.10))  # Cap at 10% of bankroll
        
        bet = self.balance * fraction
        return min(bet, 50.0)  # Hard cap at $50
    
    def find_best_market(self):
        """Find best KXBTC15M market to trade"""
        markets = self.kalshi.get_markets()
        
        if not markets:
             self.log_event("WARNING: API returned 0 markets during search", level="WARNING")
        
        now = datetime.now(timezone.utc)
        
        best_market = None
        best_time_to_close = float('inf')
        
        # Diagnostics
        closest_market_debug = None
        closest_market_ttc = float('inf')
        
        count_series = 0
        
        for m in markets:
            ticker = m.get('ticker', '')
            if not ticker.upper().startswith('KXBTC15M'):
                continue
            
            count_series += 1
            
            close_time_str = m.get('close_time')
            if not close_time_str:
                continue
            
            close_dt = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
            time_to_close = (close_dt - now).total_seconds()
            
            # WIDENED WINDOW: 2 to roughly 15 minutes
            if 120 < time_to_close < 880:
                if time_to_close < best_time_to_close:
                    best_time_to_close = time_to_close
                    best_market = m
            
            # Track closest market for debug if we fail to find one
            if 0 < time_to_close < closest_market_ttc:
                 closest_market_ttc = time_to_close
                 closest_market_debug = ticker

        if not best_market and count_series > 0:
             # Only log if we expected to find something but didn't
             # This helps debug "Singal skipped" messages
             pass 
             # I'll let the caller log "Market not found", but here I can store debug info
             # specific to why. 
             # Actually, let's just log here if we are confused. 
             # But this runs every 15s, so I don't want to spam headers unless a signal is pending.
             # The caller (run loop) knows if a signal is pending. 
             # Let's just return extra info? No, keep signature simple.
             # I will log diagnostics ONION-style only if I failed to find a market 
             # but found markets in the series.
             pass

        if not best_market and self.signals_seen > 0: # Heuristic: if we are active
             # We can't easily know if the caller HAS a signal right now without changing method signature.
             # So I will just add the debug print logic to the CALLER site in run(), 
             # OR I just log a debug line here every time we fail? No, too spammy.
             pass

        # Retaining original return, but with added logging in case of suspicious failure
        if not best_market and closest_market_debug and closest_market_ttc < 3600:
             # If we have a market within 1 hour but nothing in window
             self.log_event(f"Debug: No market in window. Closest: {closest_market_debug} in {closest_market_ttc:.1f}s", level="DEBUG")

        return best_market
    
    def get_best_price(self, ticker, direction):
        """Get best ask price for direction"""
        book = self.kalshi.get_orderbook(ticker)
        if not book:
            return None
        
        if direction == 'YES':
            # To buy YES, cross the NO bid (or use YES ask)
            no_bids = book.get('no', [])
            if no_bids:
                best_no_bid = no_bids[-1][0]
                yes_ask = (100 - best_no_bid) / 100.0
                return yes_ask + 0.03  # Add slippage
        else:
            # To buy NO, cross the YES bid
            yes_bids = book.get('yes', [])
            if yes_bids:
                best_yes_bid = yes_bids[-1][0]
                no_ask = (100 - best_yes_bid) / 100.0
                return no_ask + 0.03  # Add slippage
        
        return None
    
    def log_trade(self, trade, status, pnl=0.0):
        with open(self.log_file, 'a', newline='') as f:
            csv.writer(f).writerow([
                datetime.now().isoformat(),
                trade['ticker'],
                trade['direction'],
                trade['signal'],
                trade.get('rsi', ''),
                trade.get('return_15m', ''),
                trade['price'],
                trade['contracts'],
                status,
                pnl
            ])
    
    def settle_positions(self):
        """Check and settle expired positions"""
        now = datetime.now(timezone.utc)
        new_positions = []
        
        for pos in self.positions:
            close_time = datetime.fromisoformat(pos['close_time'].replace('Z', '+00:00'))
            
            if now > close_time + timedelta(seconds=60):
                # Guard: skip if already settled (prevents double processing)
                if pos.get('settled'):
                    continue
                
                # Try to get result
                result = self.kalshi.get_market_result(pos['ticker'])
                
                if result is None:
                    # Optional: Log that we tried but failed, to debug "zombie" trades
                    # self.log_event(f"Scanning {pos['ticker']} result... (not final yet)", level="DEBUG")
                    new_positions.append(pos)
                    continue
                
                won = (result.upper() == pos['direction'])
                payout = pos['contracts'] * 1.00 if won else 0
                profit = payout - (pos['contracts'] * pos['price'])
                
                if won:
                    self.balance += payout
                    self.wins += 1
                else:
                    self.losses += 1
                
                self.log_trade(pos, 'SETTLED', profit)
                
                settle_msg = (
                    f"\n{'='*60}\n"
                    f"{'✅ WIN' if won else '❌ LOSS'}: {pos['ticker']}\n"
                    f"   Signal: {pos['signal']}\n"
                    f"   Result: {result}\n"
                    f"   P&L: ${profit:+.2f}\n"
                    f"   Balance: ${self.balance:.2f} (W:{self.wins} L:{self.losses})\n"
                    f"{'='*60}\n"
                )
                self.log_event(settle_msg, level="SETTLED")
                
                # Mark as settled to prevent double processing
                pos['settled'] = True
                
                self.save_state()
                
                # Force stats print immediately so user sees updated win/loss
                self.print_session_stats()
                self.last_stats_print = time.time()
            else:
                new_positions.append(pos)
        
        self.positions = new_positions
    
    def log_event(self, message, level="INFO"):
        """Write to event log file AND print to console"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        
        # 1. Write to file
        with open(self.event_log, 'a') as f:
            f.write(log_line + "\n")
            
        # 2. Print to console (so user sees it matches)
        print(log_line, flush=True)
    
    def print_session_stats(self):
        """Print comprehensive session statistics"""
        runtime = time.time() - self.session_start
        hours = int(runtime // 3600)
        mins = int((runtime % 3600) // 60)
        
        total_trades = self.wins + self.losses
        win_rate = (self.wins / total_trades * 100) if total_trades > 0 else 0
        pnl = self.balance - self.initial_balance
        
        if self.last_trade_time > 0:
            last_trade_str = datetime.fromtimestamp(self.last_trade_time).strftime("%H:%M:%S")
        else:
            last_trade_str = "None"
            
        stats_msg = (
            f"\n\n{'='*60}\n"
            f"🚀 MOMENTUM BOT STATUS (Runtime: {hours}h {mins}m)\n"
            f"{'='*60}\n"
            f"  💰 Total Balance: ${self.balance:.2f} (Total P&L: ${pnl:+.2f})\n"
            f"  📈 Total Record:  {self.wins}W - {self.losses}L ({win_rate:.1f}% WR)\n"
            f"  ------------------------------------------------------------\n"
            f"  📡 Session Signals Seen:  {self.signals_seen}\n"
            f"  ✅ Session Trades Taken:  {self.signals_taken}\n"
            f"  🕒 Last Trade Time:       {last_trade_str}\n"
            f"  ⏳ Session Skipped:       {self.signals_skipped_cooldown} (Cool) + {self.signals_skipped_price} (Price)\n"
            f"  📂 Open Positions:        {len(self.positions)}\n"
            f"{'='*60}\n"
        )
        
        self.log_event(stats_msg, level="STATS")
    
    def run(self):
        banner = (
            f"\n{'='*60}\n"
            f"I am a friendly trading bot. I look for specific patterns in Bitcoin's price to make predictions.\n"
            f"I will explain everything I see and do so you can understand my decisions.\n"
            f"{'='*60}\n"
        )
        self.log_event(banner + "Bot started (Optimized Momentum Logic)")
        last_scan = 0
        last_explanation_time = 0

        
        while True:
            try:
                self.update_history()
                
                if self.ws.current_candle is None:
                    time.sleep(1)
                    continue
                
                # Check for stale data - force reconnect if needed
                staleness = time.time() - self.ws.last_update
                if staleness > 15:
                    self.log_event(f"WebSocket stale ({int(staleness)}s) - reconnecting...", level="WARNING")
                    self.ws.force_reconnect()
                    time.sleep(3)
                    continue
                
                current_price = self.ws.current_candle['close']
                indicators = self.get_current_indicators()
                signal = self.get_signal(indicators)
                
                # Status line with more info
                rsi = indicators.get('rsi_14', 0)
                ret15 = indicators.get('return_15m', 0) * 100
                ret5 = indicators.get('return_5m', 0) * 100
                cooldown_left = max(0, self.TRADE_COOLDOWN_SECONDS - (time.time() - self.last_trade_time))
                
                # Create a narrative status message
                status_msg = ""
                if cooldown_left > 0:
                     status_msg = f"I just traded, so I'm taking a short break ({int(cooldown_left)}s left) to avoid over-trading."
                elif signal:
                    status_msg = "I see a potential trade! Evaluating if the price implies a good win rate..."
                elif rsi > 70:
                    status_msg = f"The price has gone up very quickly (High RSI: {rsi:.0f}). It might be due for a drop."
                elif rsi < 30:
                    status_msg = f"The price has fallen very quickly (Low RSI: {rsi:.0f}). It might bounce back up."
                elif abs(ret15) < 0.2:
                    status_msg = "The market is very quiet right now. Waiting for some action."
                else:
                    status_msg = "Watching the market. No strong patterns detected yet."

                # Status Update (Heartbeat) - Every 60 seconds
                if time.time() - last_explanation_time > 60:
                    last_explanation_time = time.time()
                    hb_msg = f"Heartbeat: {status_msg} [BTC: ${current_price:,.0f}]"
                    self.log_event(hb_msg, level="HEARTBEAT")

                
                # Print stats every 5 minutes
                if time.time() - self.last_stats_print > 300:
                    self.last_stats_print = time.time()
                    self.print_session_stats()
                
                # Scan every 15 seconds
                if time.time() - last_scan > 15:
                    last_scan = time.time()
                    
                    # Check cooldown - avoid clustered signals
                    time_since_trade = time.time() - self.last_trade_time
                    in_cooldown = time_since_trade < self.TRADE_COOLDOWN_SECONDS
                    
                    if signal:
                        self.signals_seen += 1
                        
                        if in_cooldown:
                            self.signals_skipped_cooldown += 1
                            self.log_event(f"Signal skipped (cooldown): {signal[1]}")
                            # No need to print, the status line handles the explanation

                        elif len(self.positions) < 3:
                            direction, signal_name, expected_wr = signal
                            
                            market = self.find_best_market()
                            if not market:
                                self.log_event(f"Signal skipped (no 5-12m market found): {signal_name}\n   ⚠️ Signal triggered, but no matching market closing in 5-12 mins found.", level="WARNING")
                            
                            if market:
                                ticker = market['ticker']
                                
                                # Skip if already in this market
                                if any(p['ticker'] == ticker for p in self.positions):
                                    self.log_event(f"Signal skipped (already in market): {ticker}")
                                else:
                                    price = self.get_best_price(ticker, direction)
                                    
                                    if not price or price <= 0.10 or price >= 0.90:
                                        self.signals_skipped_price += 1
                                        skip_msg = (
                                            f"Signal skipped (bad price {price:.2f}): {signal_name}\n"
                                            f"   ⚠️ I saw an opportunity, but the price ({price:.2f}) was too expensive or too cheap to be worth it."
                                        )
                                        self.log_event(skip_msg)

                                    else:
                                        # EV check: ensure positive expected value at this price
                                        # EV = (win_rate × payout) - ((1 - win_rate) × cost)
                                        # payout = 1 - price, cost = price
                                        ev = (expected_wr * (1.0 - price)) - ((1.0 - expected_wr) * price)
                                        min_ev_threshold = 0.02  # Require 2% edge minimum
                                        
                                        if ev < min_ev_threshold:
                                            skip_msg = (
                                                f"Signal skipped (EV={ev:.1%} < {min_ev_threshold:.0%}): {signal_name} @ {price:.0%}\n"
                                                f"   🤔 I considered a trade, but the potential profit wasn't high enough for the risk."
                                            )
                                            self.log_event(skip_msg)

                                        else:
                                            # Kelly-based sizing
                                            bet_amount = self.calculate_bet_size(expected_wr, price)
                                            if bet_amount >= 5.0:
                                                contracts = int(bet_amount / price)
                                                cost = contracts * price
                                            
                                                if contracts >= 1 and cost <= self.balance:
                                                    self.balance -= cost
                                                    self.last_trade_time = time.time()
                                                    self.signals_taken += 1
                                                    
                                                    trade = {
                                                        'ticker': ticker,
                                                        'direction': direction,
                                                        'signal': signal_name,
                                                        'rsi': rsi,
                                                        'return_15m': ret15,
                                                        'price': price,
                                                        'contracts': contracts,
                                                        'close_time': market['close_time']
                                                    }
                                                    self.positions.append(trade)
                                                    self.log_trade(trade, 'OPENED')
                                                    self.save_state()
                                                    
                                                    # Detailed Trade Log
                                                    trade_msg = (
                                                        f"🚀 TRADE OPENED: {ticker} {direction} @ {price:.0%} ({signal_name})\n"
                                                        f"   Reason: {signal_name.replace('_', ' ')}\n"
                                                        f"   Wager: ${cost:.2f} (WR: {expected_wr:.1%} EV: {ev:.1%})"
                                                    )
                                                    self.log_event(trade_msg, level="TRADE")

                    
                    self.settle_positions()
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                print(f"\n\n{'='*60}")
                print("🛑 BOT STOPPED")
                print(f"   Final Balance: ${self.balance:.2f}")
                print(f"   P&L: ${self.balance - self.initial_balance:+.2f}")
                print(f"   Record: {self.wins}W - {self.losses}L")
                if self.wins + self.losses > 0:
                    print(f"   Win Rate: {self.wins/(self.wins+self.losses)*100:.1f}%")
                print(f"{'='*60}")
                break
            except Exception as e:
                print(f"\n⚠️ Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = SimpleMomentumBot()
    bot.run()
