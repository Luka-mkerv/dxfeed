import requests
import pandas as pd
from datetime import datetime, timezone

BASE_URL = 'https://demo.dxfeed.com/webservice/rest/events.json'

INSTRUMENTS = {
    'AAPL':    'AAPL',
    'TSLA':    'TSLA', 
    'EUR/USD': 'EUR/USD'
}

TIMEFRAMES = {
    '1m': '{=1m}',
    '5m': '{=5m}',
    '1h': '{=1h}'
}

# Use a full trading day — ET timezone implied by API
FROM_TIME = '2026-09-17T09:30:00'
TO_TIME   = '2026-09-17T16:00:00'


def fetch_candles(symbol, timeframe, price_type=None):
    if price_type:
        candle_symbol = f"{symbol}{{={timeframe},price={price_type}}}"
    else:
        candle_symbol = f"{symbol}{{={timeframe}}}"
    
    params = {
        'events': 'Candle',
        'symbols': candle_symbol,
        'fromTime': FROM_TIME,
        'toTime': TO_TIME
    }
    
    r = requests.get(BASE_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    
    candles = data.get('Candle', {}).get(candle_symbol, [])
    
    if not candles:
        print(f"  WARNING: No data for {candle_symbol}")
        return pd.DataFrame()
    
    df = pd.DataFrame(candles)
    df['datetime'] = pd.to_datetime(df['time'], unit='ms', utc=True)
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'count']].copy()
    df = df.sort_values('datetime').reset_index(drop=True)
    return df


def aggregate_candles(df, rule):
    df = df.copy()
    df = df.set_index('datetime')
    
    agg = df.resample(rule).agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
        count=('count', 'sum')
    ).dropna(subset=['open'])
    
    return agg.reset_index()


def compare_candles(aggregated, reported, label, tolerance=0.01):
    print(f"\n{'='*60}")
    print(f"COMPARISON: {label}")
    print('='*60)
    
    if aggregated.empty or reported.empty:
        print("  Cannot compare — missing data")
        return []
    
    reported = reported.copy()
    reported['datetime'] = pd.to_datetime(reported['datetime'], utc=True)
    reported = reported.set_index('datetime')
    
    aggregated = aggregated.set_index('datetime')
    
    anomalies = []
    
    # Find common timestamps
    common = aggregated.index.intersection(reported.index)
    print(f"  Matching timestamps: {len(common)}")
    print(f"  Aggregated candles: {len(aggregated)}")
    print(f"  Reported candles:   {len(reported)}")
    
    for ts in common:
        agg_row = aggregated.loc[ts]
        rep_row = reported.loc[ts]
        
        for field in ['open', 'high', 'low', 'close']:
            agg_val = agg_row[field]
            rep_val = rep_row[field]
            
            if rep_val == 0:
                continue
                
            diff_pct = abs(agg_val - rep_val) / rep_val * 100
            
            if diff_pct > tolerance:
                anomalies.append({
                    'timestamp': ts,
                    'field': field,
                    'aggregated': agg_val,
                    'reported': rep_val,
                    'diff_pct': diff_pct
                })
                print(f"  ANOMALY at {ts}: {field} "
                      f"aggregated={agg_val:.4f} "
                      f"reported={rep_val:.4f} "
                      f"diff={diff_pct:.3f}%")
        
        # Volume comparison
        vol_diff_pct = abs(agg_row['volume'] - rep_row['volume']) / rep_row['volume'] * 100 if rep_row['volume'] > 0 else 0
        if vol_diff_pct > 1.0:
            anomalies.append({
                'timestamp': ts,
                'field': 'volume',
                'aggregated': agg_row['volume'],
                'reported': rep_row['volume'],
                'diff_pct': vol_diff_pct
            })
            print(f"  ANOMALY at {ts}: volume "
                  f"aggregated={agg_row['volume']:.2f} "
                  f"reported={rep_row['volume']:.2f} "
                  f"diff={vol_diff_pct:.3f}%")
    
    if not anomalies:
        print("  No anomalies found")
    
    return anomalies


def print_candles(df, label):
    print(f"\n{'='*60}")
    print(f"{label} — {len(df)} candles")
    print('='*60)
    if df.empty:
        print("  No data")
        return
    print(df.to_string(index=True))



def main():
    print(f"Fetching candles from {FROM_TIME} to {TO_TIME}")
    
    import os
    os.makedirs('task1/data', exist_ok=True)
    
    all_anomalies = {}
    
    for name, symbol in INSTRUMENTS.items():
        print(f"\nFetching {name}...")
        price_type = 'bid' if name == 'EUR/USD' else None
        
        dfs = {}
        for tf_name in TIMEFRAMES:
            df = fetch_candles(symbol, tf_name, price_type)
            dfs[tf_name] = df
            if not df.empty:
                filename = f"task1/data/{name.replace('/', '_')}_{tf_name}.csv"
                df.to_csv(filename, index=False)
                print(f"  {tf_name}: {len(df)} candles")
        
        # Compare 1m aggregated to 5m reported
        if not dfs['1m'].empty and not dfs['5m'].empty:
            agg_5m = aggregate_candles(dfs['1m'], '5min')
            anomalies_5m = compare_candles(
                agg_5m, dfs['5m'], 
                f"{name}: 1m aggregated vs 5m reported"
            )
            all_anomalies[f"{name}_1m_vs_5m"] = anomalies_5m
        
        # Compare 5m aggregated to 1h reported
        if not dfs['5m'].empty and not dfs['1h'].empty:
            agg_1h = aggregate_candles(dfs['5m'], '1h')
            anomalies_1h = compare_candles(
                agg_1h, dfs['1h'],
                f"{name}: 5m aggregated vs 1h reported"
            )
            all_anomalies[f"{name}_5m_vs_1h"] = anomalies_1h
    
    # Summary
    print(f"\n{'#'*60}")
    print("ANOMALY SUMMARY")
    print('#'*60)
    total = sum(len(v) for v in all_anomalies.values())
    print(f"Total anomalies found: {total}")
    for key, anomalies in all_anomalies.items():
        print(f"  {key}: {len(anomalies)} anomalies")

if __name__ == '__main__':
    main()