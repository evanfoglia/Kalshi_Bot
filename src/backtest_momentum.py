"""
Momentum Strategy Backtest
Tests simple heuristic rules for consistent win-rate trading on KXBTC15M
"""

import pandas as pd
import numpy as np
import sys
sys.path.insert(0, 'src')
from features import add_technical_indicators
from strategy import get_signal

def test_momentum_strategies(df):
    """Test various momentum rules and report win rates"""
    
    results = []
    
    # Prepare data - we need 15 min lookahead for settlement
    df = df.copy()
    df['future_close'] = df['close'].shift(-15)
    df['won_yes'] = (df['future_close'] > df['close']).astype(int)  # BTC went up
    df['won_no'] = (df['future_close'] <= df['close']).astype(int)  # BTC went down or flat
    df = df.dropna()
    
    print("="*70)
    print("MOMENTUM STRATEGY BACKTEST")
    print("="*70)
    print(f"Testing on {len(df):,} 15-minute windows\n")
    
    # ============================================================
    # STRATEGY 0: CURRENT BOT LOGIC (Shared Code)
    # ============================================================
    print("STRATEGY 0: CURRENT BOT CONFIGURATION (Exact Match)")
    print("-"*50)
    
    # We'll apply the exact get_signal logic to every row
    # This is slower but guarantees 100% logic match
    bot_wins = 0
    bot_trades = 0
    
    for idx, row in df.iterrows():
        # Construct simplified indicators dict
        indicators = {
            'rsi_14': row['rsi_14'],
            'return_15m': row['return_15m'],
            'return_5m': row['return_5m']
        }
        
        signal = get_signal(indicators)
        if signal:
            direction, name, _ = signal
            bot_trades += 1
            if direction == 'NO':
                if row['won_no']: bot_wins += 1
            else:
                if row['won_yes']: bot_wins += 1
                
    if bot_trades > 0:
        wr = bot_wins / bot_trades * 100
        print(f"  Exact Bot Logic: {bot_wins}/{bot_trades} trades = {wr:.1f}% Win Rate")
    else:
        print("  Exact Bot Logic: No trades triggered in this period.")

    print()
    
    # ============================================================
    # STRATEGY 1: Simple Momentum Continuation
    # ============================================================
    print("STRATEGY 1: Momentum Continuation")
    print("-"*50)
    
    for threshold in [0.002, 0.003, 0.004, 0.005]:
        # Bet YES when recent momentum is positive
        mask_yes = df['return_5m'] > threshold
        if mask_yes.sum() > 0:
            wins = df.loc[mask_yes, 'won_yes'].sum()
            total = mask_yes.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'Momentum UP > {threshold*100:.1f}%',
                'direction': 'YES',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  5m return > {threshold*100:.2f}% → Bet YES: {wins}/{total} = {wr:.1f}% win rate")
        
        # Bet NO when recent momentum is negative
        mask_no = df['return_5m'] < -threshold
        if mask_no.sum() > 0:
            wins = df.loc[mask_no, 'won_no'].sum()
            total = mask_no.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'Momentum DOWN < -{threshold*100:.1f}%',
                'direction': 'NO',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  5m return < -{threshold*100:.2f}% → Bet NO:  {wins}/{total} = {wr:.1f}% win rate")
    
    print()
    
    # ============================================================
    # STRATEGY 2: Mean Reversion After Extreme Moves
    # ============================================================
    print("STRATEGY 2:    # Reversion after large move (Mean Reversion)")
    print("    # ------------------------------------------------------------")
    
    # Drop logic (Bet YES)
    for threshold in [0.003, 0.004, 0.005, 0.006, 0.008]: # Added 0.003 (Aggressive)
        mask = df['return_15m'] < -threshold
        if mask.sum() > 0:
            wins = df.loc[mask, 'won_yes'].sum()
            total = mask.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'Reversion after DOWN < -{threshold*100:.1f}%',
                'direction': 'YES',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  15m return < -{threshold*100:.2f}% → Bet YES (reversal): {wins}/{total} = {wr:.1f}% win rate")

    # Spike logic (Bet NO)
    for threshold in [0.004, 0.005, 0.006, 0.008]: # Added 0.008 (Turbo Mode)
        mask = df['return_15m'] > threshold
        if mask.sum() > 0:
            wins = df.loc[mask, 'won_no'].sum()
            total = mask.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'Reversion after UP > {threshold*100:.1f}%',
                'direction': 'NO',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  15m return > {threshold*100:.2f}% → Bet NO (reversal): {wins}/{total} = {wr:.1f}% win rate")
    
    print()
    
    # ============================================================
    # STRATEGY 3: RSI Extreme Zones
    # ============================================================
    print("STRATEGY 3: RSI Extremes")
    print("-"*50)
    
    for rsi_low, rsi_high in [(20, 80), (25, 75), (30, 70)]:
        # Oversold - bet YES (expect bounce)
        mask = df['rsi_14'] < rsi_low
        if mask.sum() > 0:
            wins = df.loc[mask, 'won_yes'].sum()
            total = mask.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'RSI < {rsi_low}',
                'direction': 'YES',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  RSI < {rsi_low} → Bet YES (oversold bounce): {wins}/{total} = {wr:.1f}% win rate")
        
        # Overbought - bet NO (expect pullback)
        mask = df['rsi_14'] > rsi_high
        if mask.sum() > 0:
            wins = df.loc[mask, 'won_no'].sum()
            total = mask.sum()
            wr = wins / total * 100
            print(f"  RSI > {rsi_high} → Bet NO (overbought pullback): {wins}/{total} = {wr:.1f}% win rate")

    print()
    print("STRATEGY 3B: RSI + Momentum Confirmation (Refined)")
    print("-"*50)
    
    for rsi_val in [65, 70, 75, 80]:
        # RSI strict + 5m downturn (Matched to Bot: Any red candle < 0)
        mask = (df['rsi_14'] > rsi_val) & (df['return_5m'] < 0) 
        if mask.sum() > 0:
            wins = df.loc[mask, 'won_no'].sum()
            total = mask.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'RSI > {rsi_val} + 5m Dip',
                'direction': 'NO',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  RSI > {rsi_val} + 5m Dip (< -0.1%) → Bet NO: {wins}/{total} = {wr:.1f}% win rate")
            
    # Extreme RSI (No Confirmation)
    mask = df['rsi_14'] > 80
    if mask.sum() > 0:
        wins = df.loc[mask, 'won_no'].sum()
        total = mask.sum()
        wr = wins / total * 100
        results.append({
            'strategy': 'RSI > 80 (No Conf)',
            'direction': 'NO',
            'trades': total,
            'wins': wins,
            'win_rate': wr
        })
        print(f"  RSI > 80 (No Confirmation) → Bet NO: {wins}/{total} = {wr:.1f}% win rate")
    
    print()
    
    # ============================================================
    # STRATEGY 4: Low Volatility + Trend
    # ============================================================
    print("STRATEGY 4: Low Volatility + Micro-Trend")
    print("-"*50)
    
    vol_25th = df['vol_15'].quantile(0.25)
    low_vol_mask = df['vol_15'] < vol_25th
    
    # In low vol, bet with micro-trend
    for threshold in [0.001, 0.0015, 0.002]:
        mask = low_vol_mask & (df['return_5m'] > threshold)
        if mask.sum() > 0:
            wins = df.loc[mask, 'won_yes'].sum()
            total = mask.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'LowVol + Up > {threshold*100:.2f}%',
                'direction': 'YES',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  Low vol + 5m up > {threshold*100:.2f}% → Bet YES: {wins}/{total} = {wr:.1f}% win rate")
        
    print("STRATEGY 5: ALWAYS ACTIVE (Market Making)")
    print("-"*50)
    
    # Always Fade (Bet Against 15m Move)
    # If 15m is Green (>0), Bet NO.
    mask = df['return_15m'] > 0
    if mask.sum() > 0:
        wins = df.loc[mask, 'won_no'].sum()
        total = mask.sum()
        wr = wins / total * 100
        print(f"  ALWAYS FADE (Up -> NO): {wins}/{total} = {wr:.1f}% win rate")
        
    # If 15m is Red (<0), Bet YES.
    mask = df['return_15m'] < 0
    if mask.sum() > 0:
        wins = df.loc[mask, 'won_yes'].sum()
        total = mask.sum()
        wr = wins / total * 100
        print(f"  ALWAYS FADE (Down -> YES): {wins}/{total} = {wr:.1f}% win rate")
    
    print()
    
    # Always Follow (Trend Following)
    # If 15m is Green (>0), Bet YES.
    mask = df['return_15m'] > 0
    if mask.sum() > 0:
        wins = df.loc[mask, 'won_yes'].sum()
        total = mask.sum()
        wr = wins / total * 100
        print(f"  ALWAYS FOLLOW (Up -> YES): {wins}/{total} = {wr:.1f}% win rate")
        
    # If 15m is Red (<0), Bet NO.
    mask = df['return_15m'] < 0
    if mask.sum() > 0:
        wins = df.loc[mask, 'won_no'].sum()
        total = mask.sum()
        wr = wins / total * 100
        print(f"  ALWAYS FOLLOW (Down -> NO): {wins}/{total} = {wr:.1f}% win rate")

    
    print()
    
    # ============================================================
    # STRATEGY 5: Taker Ratio (Buy Pressure) 
    # ============================================================
    print("STRATEGY 5: Buy Pressure (Taker Ratio)")
    print("-"*50)
    
    for ratio in [0.55, 0.60, 0.65]:
        # High buy pressure - bet YES
        mask = df['taker_ratio'] > ratio
        if mask.sum() > 0:
            wins = df.loc[mask, 'won_yes'].sum()
            total = mask.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'Taker ratio > {ratio:.0%}',
                'direction': 'YES',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  Taker ratio > {ratio:.0%} → Bet YES: {wins}/{total} = {wr:.1f}% win rate")
        
        # Low buy pressure - bet NO
        mask = df['taker_ratio'] < (1 - ratio)
        if mask.sum() > 0:
            wins = df.loc[mask, 'won_no'].sum()
            total = mask.sum()
            wr = wins / total * 100
            results.append({
                'strategy': f'Taker ratio < {1-ratio:.0%}',
                'direction': 'NO',
                'trades': total,
                'wins': wins,
                'win_rate': wr
            })
            print(f"  Taker ratio < {1-ratio:.0%} → Bet NO:  {wins}/{total} = {wr:.1f}% win rate")
    
    print()
    
    # ============================================================
    # FIND BEST STRATEGIES
    # ============================================================
    print("="*70)
    print("TOP STRATEGIES BY WIN RATE (min 50 trades)")
    print("="*70)
    
    df_results = pd.DataFrame(results)
    df_results = df_results[df_results['trades'] >= 50]
    df_results = df_results.sort_values('win_rate', ascending=False)
    
    print(f"\n{'Strategy':<40} | {'Dir':<4} | {'Trades':<7} | {'Win Rate':<8}")
    print("-"*70)
    for _, row in df_results.head(10).iterrows():
        print(f"{row['strategy']:<40} | {row['direction']:<4} | {row['trades']:<7} | {row['win_rate']:.1f}%")
    
    return df_results

def simulate_profit(df, strategy_mask, direction, bet_size=10):
    """Simulate profit for a strategy assuming fair pricing"""
    df = df.copy()
    df['future_close'] = df['close'].shift(-15)
    df['won_yes'] = (df['future_close'] > df['close']).astype(int)
    df['won_no'] = (df['future_close'] <= df['close']).astype(int)
    df = df.dropna()
    
    trades = df[strategy_mask]
    if len(trades) == 0:
        return 0, 0, 0
    
    if direction == 'YES':
        wins = trades['won_yes'].sum()
    else:
        wins = trades['won_no'].sum()
    
    total = len(trades)
    win_rate = wins / total
    
    # Assume 50% contract price (fair value)
    # Win: +$0.50 per contract, Lose: -$0.50 per contract
    pnl = wins * 0.50 - (total - wins) * 0.50
    pnl_per_trade = pnl / total
    
    # With bet_size dollars per trade
    total_pnl = pnl_per_trade * 2 * bet_size * total  # x2 because we normalize to $0.50
    
    return total, win_rate, total_pnl

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Momentum Strategy Backtest')
    parser.add_argument('--days', type=int, default=None,
                        help='Number of days to backtest (e.g., 7, 14, 30)')
    parser.add_argument('--hours', type=int, default=None,
                        help='Number of hours to backtest (e.g., 1, 6, 24)')
    args = parser.parse_args()
    
    # Determine time window
    if args.hours:
        minutes_to_keep = args.hours * 60
        label = f"{args.hours} hour(s)"
    elif args.days:
        minutes_to_keep = args.days * 24 * 60
        label = f"{args.days} day(s)"
    else:
        minutes_to_keep = 30 * 24 * 60  # Default 30 days
        label = "30 days"
    
    print(f"📊 Loading data (last {label})...")
    df = pd.read_csv("data/btc_1min_data.csv", index_col='timestamp', parse_dates=True)
    
    # Filter to requested time window from the END of the data (most recent)
    if len(df) > minutes_to_keep:
        df = df.iloc[-minutes_to_keep:]
        print(f"   Filtered to {len(df):,} rows ({label})")
    
    df = add_technical_indicators(df).dropna()
    
    results = test_momentum_strategies(df)
    
    print("\n")
    print("="*70)
    print("💡 RECOMMENDATION")
    print("="*70)
    
    # Get best strategy
    if len(results) > 0:
        best = results.iloc[0]
        print(f"\nBest strategy: {best['strategy']}")
        print(f"Direction: {best['direction']}")
        print(f"Historical win rate: {best['win_rate']:.1f}%")
        print(f"Sample size: {best['trades']} trades")
        
        if best['win_rate'] > 55:
            edge = best['win_rate'] - 50
            print(f"\nEstimated edge: ~{edge:.1f}% per trade")
            print(f"At $10/trade, expected profit: ~${edge/100 * 10:.2f}/trade")

