"""
Shared API Classes for Kalshi Trading Bots
Contains WebSocket client and Kalshi API wrapper
"""

import time
import json
import requests
import pandas as pd
import websocket
import threading


class BinanceWSServer:
    """Kraken WebSocket Client (no geo-restrictions, works globally)"""
    
    def __init__(self, symbol="XBT/USD", verify_ssl=False):
        # Kraken WebSocket - no geographic restrictions
        self.url = "wss://ws.kraken.com"
        self.symbol = symbol
        self.current_candle = None
        self.last_update = 0
        self.last_heartbeat = 0
        self.ws = None
        self.is_running = False
        self.verify_ssl = verify_ssl
        self.reconnect_count = 0
        self.subscribed = False
        
        # Track OHLCV for the current minute
        self._current_minute = None
        self._minute_open = None
        self._minute_high = None
        self._minute_low = None
        self._minute_volume = 0
        self._taker_buy_volume = 0
        
    def on_message(self, ws, message):
        data = json.loads(message)
        self.last_update = time.time()
        
        # Handle subscription confirmation
        if isinstance(data, dict):
            if data.get('event') == 'subscriptionStatus':
                if data.get('status') == 'subscribed':
                    self.subscribed = True
                    print(f"✅ Subscribed to {data.get('pair')}")
                return
            if data.get('event') in ['heartbeat', 'systemStatus']:
                self.last_heartbeat = time.time()
                return
        
        # Trade data comes as array: [channelID, [[price, volume, time, side, orderType, misc], ...], channelName, pair]
        if isinstance(data, list) and len(data) >= 4:
            channel_name = data[2] if len(data) > 2 else None
            if channel_name == 'trade':
                trades = data[1]
                for trade in trades:
                    price = float(trade[0])
                    qty = float(trade[1])
                    trade_time = pd.to_datetime(float(trade[2]), unit='s')
                    side = trade[3]  # 'b' = buy, 's' = sell
                    
                    current_minute = trade_time.floor('min')
                    
                    # New minute started
                    if self._current_minute is not None and current_minute != self._current_minute:
                        if self.current_candle:
                            self.current_candle['is_closed'] = True
                        self._minute_open = price
                        self._minute_high = price
                        self._minute_low = price
                        self._minute_volume = 0
                        self._taker_buy_volume = 0
                    
                    self._current_minute = current_minute
                    
                    if self._minute_open is None:
                        self._minute_open = price
                        self._minute_high = price
                        self._minute_low = price
                    
                    self._minute_high = max(self._minute_high, price)
                    self._minute_low = min(self._minute_low, price)
                    self._minute_volume += qty
                    if side == 'b':  # Taker is buying
                        self._taker_buy_volume += qty
                    
                    self.current_candle = {
                        'timestamp': self._current_minute,
                        'open': self._minute_open,
                        'high': self._minute_high,
                        'low': self._minute_low,
                        'close': price,
                        'volume': self._minute_volume,
                        'taker_buy_base': self._taker_buy_volume,
                        'is_closed': False
                    }
    
    def on_ping(self, ws, message):
        self.last_heartbeat = time.time()
    
    def on_pong(self, ws, message):
        self.last_heartbeat = time.time()
    
    def on_error(self, ws, error):
        print(f"\n⚠️ WS Error: {error}")
        
    def on_close(self, ws, close_status_code, close_msg):
        print(f"\n🔌 WS Closed (code={close_status_code})")
        
    def on_open(self, ws):
        self.reconnect_count += 1
        print(f"\n✅ WS Connected to Kraken (attempt #{self.reconnect_count})")
        
        # Subscribe to BTC/USD trades
        subscribe_msg = {
            "event": "subscribe",
            "pair": [self.symbol],
            "subscription": {"name": "trade"}
        }
        ws.send(json.dumps(subscribe_msg))
        print(f"📡 Subscribing to {self.symbol} trades...")
        
    def _run(self):
        import ssl
        while self.is_running:
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    on_open=self.on_open,
                    on_ping=self.on_ping,
                    on_pong=self.on_pong
                )
                ssl_opts = {} if self.verify_ssl else {"cert_reqs": ssl.CERT_NONE}
                self.ws.run_forever(sslopt=ssl_opts, ping_interval=20, ping_timeout=10)
            except Exception as e:
                print(f"\n⚠️ WS Exception: {e}")
            
            if self.is_running:
                print("🔄 WS reconnecting in 2s...")
                time.sleep(2)
    
    def force_reconnect(self):
        """Force reconnection when stale"""
        print("\n🔄 Forcing WebSocket reconnect...")
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        
    def start(self):
        if self.is_running: return
        self.is_running = True
        self.last_heartbeat = time.time()
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()
        print(f"⚡ WebSocket started: {self.url}")

    def stop(self):
        self.is_running = False
        if self.ws:
            self.ws.close()


class KalshiAPI:
    def __init__(self):
        # Revert to unified API endpoint
        self.BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
        # OPTIMIZATION: Reuse connections via Session
        self.session = requests.Session()
    
    def get_markets(self, series_ticker="KXBTC15M"):
        url = f"{self.BASE_URL}/markets"
        # Increased limit to 1000 to catch ALL markets in the series.
        # This prevents buried active markets from being missed.
        params = {"series_ticker": series_ticker, "limit": 1000}
        resp = self.session.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ API Error (get_markets): {resp.status_code} {resp.text}")
            return []
        
        # Return all markets from the series, let the evaluator filter further
        return resp.json().get('markets', [])
    
    def get_orderbook(self, ticker):
        url = f"{self.BASE_URL}/markets/{ticker}/orderbook"
        resp = self.session.get(url, timeout=5)
        return resp.json().get('orderbook', {}) if resp.status_code == 200 else None

    def get_market_result(self, ticker):
        """Fetch result for a settled market"""
        url = f"{self.BASE_URL}/markets/{ticker}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                market = resp.json().get('market', {})
                status = market.get('status')
                if status == 'finalized':
                    return market.get('result')
                # Optional: print(f"DEBUG: Market {ticker} status is '{status}' (not finalized)")
            else:
                print(f"⚠️ API Error (get_market_result): {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"⚠️ API Exception (get_market_result): {e}")
        return None
