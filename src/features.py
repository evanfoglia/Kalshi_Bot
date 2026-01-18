"""
Shared Feature Engineering Logic
Ensures consistency between Training and Live Trading
"""

import pandas as pd
import numpy as np

def add_technical_indicators(df):
    """
    Adds technical indicators to a DataFrame.
    Expects columns: ['open', 'high', 'low', 'close', 'volume', 'taker_buy_base']
    """
    df = df.copy()
    
    # Moving Averages (Relative to current price)
    df['ma_5_rel'] = (df['close'] - df['close'].rolling(5).mean()) / df['close'].rolling(5).mean()
    df['ma_15_rel'] = (df['close'] - df['close'].rolling(15).mean()) / df['close'].rolling(15).mean()
    df['ma_30_rel'] = (df['close'] - df['close'].rolling(30).mean()) / df['close'].rolling(30).mean()
    
    # Momentum
    df['return_5m'] = df['close'].pct_change(5)
    df['return_15m'] = df['close'].pct_change(15)
    
    # Volatility
    df['vol_15'] = df['close'].rolling(15).std() / df['close']
    df['vol_60'] = df['close'].rolling(60).std() / df['close']
    
    # ATR (Average True Range) - Better volatility measure
    if 'high' in df.columns and 'low' in df.columns:
        true_range = df['high'] - df['low']
        df['atr_14'] = true_range.rolling(14).mean() / df['close']
    else:
        df['atr_14'] = df['vol_15']  # Fallback
    
    # Volatility Regime Detection (1 = high vol, 0 = normal)
    vol_75th = df['vol_15'].rolling(100, min_periods=20).quantile(0.75)
    df['high_vol_regime'] = (df['vol_15'] > vol_75th).astype(float)
    df['high_vol_regime'] = df['high_vol_regime'].fillna(0)
    
    # RSI
    delta = df['close'].diff()
    # RSI (Wilder's Smoothing - Matches TradingView)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # Use alpha=1/14 which is equivalent to Wilder's N=14
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi_14'] = 100 - (100 / (1 + rs))
    df['rsi_14'] = df['rsi_14'].fillna(50)
    
    # Volume & Sentiment
    df['vol_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
    df['taker_ratio'] = df['taker_buy_base'] / df['volume'].replace(0, np.nan)
    df['taker_ratio'] = df['taker_ratio'].fillna(0.5)
    
    # Momentum Confluence (0 = bearish, 1 = bullish)
    df['momentum_confluence'] = (
        (df['return_5m'] > 0).astype(float) +
        (df['return_15m'] > 0).astype(float) +
        (df['ma_5_rel'] > 0).astype(float)
    ) / 3
    df['momentum_confluence'] = df['momentum_confluence'].fillna(0.5)
    
    # Time features
    if isinstance(df.index, pd.DatetimeIndex):
        df['hour'] = df.index.hour
    else:
        df['hour'] = 0
        
    return df

# Updated feature list with new indicators
FEATURE_COLS = [
    'ma_5_rel', 'ma_15_rel', 'ma_30_rel', 'return_5m', 'return_15m', 
    'vol_15', 'vol_60', 'atr_14', 'high_vol_regime', 'rsi_14', 
    'vol_ratio', 'taker_ratio', 'momentum_confluence', 'hour', 
    'close', 'strike_offset', 'minutes_to_expiry'
]
