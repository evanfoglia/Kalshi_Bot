"""
BTC Data Collector for Backtesting
Fetches historical 1-minute candles from Binance
"""

import requests
import pandas as pd
import time
from datetime import datetime, timedelta, timezone
import os

class BinanceDataCollector:
    BASE_URL = "https://api.binance.us/api/v3/klines"
    SYMBOL = "BTCUSDT"
    INTERVAL = "1m"
    
    def fetch_candles(self, start_time, end_time, limit=1000):
        params = {
            "symbol": self.SYMBOL,
            "interval": self.INTERVAL,
            "startTime": int(start_time.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000),
            "limit": limit
        }
        resp = requests.get(self.BASE_URL, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return []
    
    def fetch_historical_data(self, days=30):
        all_candles = []
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days)
        current_start = start_time
        
        print(f"📊 Fetching {days} days of BTC 1-min data...")
        
        request_count = 0
        while current_start < end_time:
            current_end = min(current_start + timedelta(minutes=1000), end_time)
            candles = self.fetch_candles(current_start, current_end)
            
            if candles:
                all_candles.extend(candles)
                request_count += 1
                if request_count % 10 == 0:
                    print(f"   Fetched {len(all_candles):,} candles...")
            
            current_start = current_end
            time.sleep(0.1)
        
        print(f"✅ Total candles: {len(all_candles):,}")
        return all_candles
    
    def to_dataframe(self, candles):
        df = pd.DataFrame(candles, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        df.set_index('timestamp', inplace=True)
        return df

def main():
    collector = BinanceDataCollector()
    raw = collector.fetch_historical_data(days=30)
    df = collector.to_dataframe(raw)
    
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    df.to_csv("data/btc_1min_data.csv")
    print(f"💾 Saved data/btc_1min_data.csv ({len(df):,} rows)")

if __name__ == "__main__":
    main()
