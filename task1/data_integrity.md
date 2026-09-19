# Task 1 — Data Consistency & Integrity Investigation

## Overview

Investigation of dxFeed demo API candle data consistency across timeframes and instruments.

## Instruments

| Instrument | Type                  | Symbol Format            |
| ---------- | --------------------- | ------------------------ |
| AAPL       | US large cap stock    | `AAPL{=1m}`              |
| TSLA       | High-volatility stock | `TSLA{=1m}`              |
| EUR/USD    | FX pair               | `EUR/USD{=1m,price=bid}` |

**Note on instrument selection:** The task required one FX pair and one high-volatility instrument. dxFeed demo does not expose candle data for crypto (BTC/USD, ETH/USD returned 0 candles). EUR/USD requires `price=bid` — plain `EUR/USD{=1m}` returns no data. This was itself documented as a finding.

## Data Collected

* Date: 2026-09-17 (Thursday)
* Window: The request used timezone-less timestamps (`2026-09-17T09:30:00` to `2026-09-17T16:00:00`). The API returned data covering approximately 14:30–21:00 UTC, corresponding to 10:30–17:00 EDT on September 17, 2026. Therefore, the dataset does not represent the full 09:30–16:00 EDT regular trading session.
* Timeframes: 1-minute, 5-minute, 1-hour
* Output: `task1/data/` — 9 CSV files

## Methodology

1. Pulled 1m, 5m, 1h candles for all 3 instruments
2. Aggregated 1m candles into 5m buckets using pandas resample
3. Compared aggregated vs reported 5m candles (OHLCV)
4. Aggregated 5m candles into 1h buckets
5. Compared aggregated vs reported 1h candles
6. Checked for gaps, duplicates, timestamp irregularities
7. Tested weekend behavior for all 3 instruments
8. Tested partial candle behavior by cutting `toTime` mid-candle
9. Tested quote staleness during market closure

## Aggregation Rules

```text
open   = first 1m candle open
high   = max of all 1m highs
low    = min of all 1m lows
close  = last 1m candle close
volume = sum of all 1m volumes
```

## Findings

### Finding 1 — Missing 1m Intervals in After-Hours Data

**Observed fact:** Missing 1-minute intervals after the 16:00 EDT regular-session close. The raw UTC interval range is approximately 20:16–20:56 UTC, corresponding to approximately 16:16–16:56 EDT on September 17, 2026.

**Evidence:**

* AAPL: 8 missing 1-minute intervals (six 2-minute gaps + one 3-minute gap), all between approximately 20:16–20:56 UTC (16:16–16:56 EDT)
* TSLA: 4 missing intervals, all after the 16:00 EDT regular-session close
* EUR/USD: 0 missing intervals during the tested window

**Interpretation:** After-hours trading is sparse. Minutes with zero trades produce no candle. This is likely expected behavior, but it is not documented in the demo API documentation.

**Operational implication:** Clients assuming continuous 1m candles across the full trading session will encounter silent gaps in after-hours windows. Automated strategies must explicitly handle missing intervals.

---

### Finding 2 — Volume Discrepancy at Session Boundary (Investigation Inconclusive)

**Observed fact:** For AAPL, the reported 1h candle **starting at 20:00 UTC (16:00 EDT)** did not match the sum of the 5m candles within that hour.

* 5m aggregated volume: 10,337,956
* 1h reported volume: 10,531,811
* Difference: ~193,855 (~1.841%)

**Investigation:** We attempted to identify a causal explanation. One hypothesis was that closing auction volume was reported into a different time bucket. However, this could not be confirmed from the available data.

**Conclusion:** The discrepancy is real and observed. The cause was not conclusively established. This should be investigated further with access to tick-level data or internal feed logs.

**Operational implication:** End-of-day volume figures in hourly candles may not precisely match aggregated sub-hour candles at session close. Clients relying on hourly candles for precise volume accounting should verify against a secondary source.

---

### Finding 3 — Quote Timestamp Absent During Market Closure

**Observed fact:** During market closure (Saturday 2026-09-19), AAPL returned bid/ask values with `time=None`.

```text
bid=334.75  ask=334.88  time=None
```

**Interpretation:** The cause — whether the system replays the last known quote, retains it in cache, or serves it from another source — could not be determined from the available evidence.

**Operational implication:** Without a timestamp, clients cannot reliably determine quote freshness. A system consuming this data has no programmatic way to distinguish a live quote from a stale one. This is a silent staleness risk.

---

### Finding 4 — Timezone Behavior

**Observed fact:** In the tested requests, timestamps were timezone-less (no explicit offset). For the main candle request (`fromTime=2026-09-17T09:30:00` to `toTime=2026-09-17T16:00:00`), the API returned data covering approximately 14:30–21:00 UTC, corresponding to 10:30–17:00 EDT on September 17, 2026. This describes the API's actual behavior for the tested request, not an assumption about intended timezone semantics.

**Evidence:** Request `fromTime=2026-09-17T10:00:00` (no offset) returned first candle at 15:00:00 UTC, which corresponds to 10:00 ET (UTC−5).

**Limitation:** This was observed in a specific set of test requests against the demo endpoint. Whether this reflects a documented API-wide rule or demo-specific behavior was not confirmed from available documentation.

**Operational implication:** Clients outside the US sending timestamps without explicit timezone offsets may receive data for unintended time windows with no error or warning. Explicit UTC offsets (e.g. `2026-09-17T15:00:00Z`) are recommended.

---

### Finding 5 — Partial Candle Suppression

**Observed fact:** When `toTime` falls within an incomplete candle interval, the API does not return a partial candle. The last returned candle is the last complete interval before `toTime`.

**Evidence:** Request with `toTime=10:32 ET` (mid 10:30–10:35 candle):

* Last candle returned: 10:30 ET (complete)
* The 10:30–10:32 data was not returned

Compared to clean request `toTime=10:35 ET`:

* Same 10:30 candle returned with higher volume and count
* Confirming additional trades occurred in 10:32–10:35 that were absent from the partial-window request

**Operational implication:** Clients querying up to the current moment will silently receive data only up to the last complete candle. The lag between the requested time and the last returned candle can be up to the full candle interval (e.g. up to 5 minutes for 5m candles). No warning or indicator is returned to signal this suppression.

---

### Investigated and Retracted: Boundary Candle Hypothesis

During investigation, we observed that a 1-hour window returned 13 five-minute candles and suspected this indicated a boundary inclusion defect causing double-counting in sequential queries.

**Retraction:** Further investigation showed that candle timestamps represent interval start times. The 21:00 candle is a new interval beginning at that timestamp, not a duplicate of the previous window. The 1-minute data was truncated at the boundary, which prevented exact reconstruction of the larger interval. The hypothesis could not be proven from the available evidence.

**Lesson:** The apparent anomaly was a methodological artifact of how we constructed the comparison, not a confirmed data integrity defect. This is documented here as a methodological lesson rather than a finding.

## What Was Confirmed Correct

* **OHLC integrity:** 0 violations across all instruments and timeframes
* **Timestamp ordering:** No duplicates, no out-of-order timestamps across any instrument or timeframe
* **Weekend handling:** US equities correctly return 0 candles on weekends. EUR/USD correctly returns candles when the FX session reopens Sunday ~21:00 UTC
* **Gap behavior:** After-hours gaps are consistent with zero-trade minutes, not feed errors

## Limitations

* Crypto instruments (BTC/USD, ETH/USD) unavailable on demo — cross-asset class testing was limited
* Partial candle behavior was tested against historical data rather than during a live market session
* Closing auction volume discrepancy could not be traced to root cause without tick-level data
* Timezone behavior observed empirically — not confirmed against official API documentation

## How to Run

```bash
cd ~/Projects/dxfeed
source venv/bin/activate
python3 task1/analyzer.py
```

Output: CSV files saved to `task1/data/`

## Tools Used

* Python 3, requests, pandas
* dxFeed demo REST API: `https://demo.dxfeed.com/webservice/rest/events.json`
* No authentication required
