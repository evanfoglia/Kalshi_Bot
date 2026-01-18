"""
Shared Trading Strategy Logic
Used by both bot_momentum.py (live trading) and backtest_momentum.py (simulation)
to ensure 100% logic parity.
"""

def get_signal(indicators, calibrated_rates=None):
    """
    Generate trading signal based on OPTIMIZED high win-rate rules.
    Returns: (direction, signal_name, expected_win_rate) or None
    
    Win rates can be passed in from recent backtest calibration.
    """
    if calibrated_rates is None:
        calibrated_rates = {}
        
    rsi = indicators.get('rsi_14', 50)
    return_15m = indicators.get('return_15m', 0)
    return_5m = indicators.get('return_5m', 0)
    
    # === OVERBOUGHT SIGNALS (Bet NO) ===
    
    # 1. THE GOLDEN SIGNAL: RSI > 80 + Dip (Red Candle)
    # Backtest WR: 80.6% (180 trades)
    if rsi > 80 and return_5m < 0:
        wr = calibrated_rates.get('rsi_80_confirm', 0.806)
        return ('NO', f'RSI={rsi:.0f}>80+DIP_GOLD', wr)
    
    # 2. RSI > 75 + Dip (High Confidence)
    # Backtest WR: 77.7% (373 trades)
    if rsi > 75 and return_5m < 0:
        wr = calibrated_rates.get('rsi_75_confirm', 0.777)
        return ('NO', f'RSI={rsi:.0f}>75+DIP', wr)
        
    # 3. RSI > 70 + Dip (Turbo Mode)
    # Backtest WR: 71.9% (720 trades)
    if rsi > 70 and return_5m < 0:
        wr = calibrated_rates.get('rsi_70_confirm', 0.719)
        return ('NO', f'RSI={rsi:.0f}>70+DIP', wr)
    
    # === MEAN REVERSION SIGNALS (Bet YES) ===
    
    # 4. Big Drop Mean Reversion (-0.3%)
    # Backtest WR: 69.6% (3072 trades)
    if return_15m < -0.003:
        wr = calibrated_rates.get('15m_drop', 0.696)
        return ('YES', f'15m_drop={return_15m*100:.2f}%', wr)
    
    # NOTE: "Big Pump Fade" signal removed (only ~65% WR, dragged down average)
    
    return None

