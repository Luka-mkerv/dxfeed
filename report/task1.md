# Task 1 — Data Consistency, Real-Time Behavior & Operational Review

## 1. Objective

Assess the dxFeed demo REST candle API for:

- Cross-timeframe data consistency and integrity
- Behavior under concurrent request load
- Operational risks relevant to support and client integrations
- Incident-handling reasoning via a simulated scenario
- Product improvements grounded in observed behavior

This report synthesizes the investigation. Detailed evidence lives under [`task1/`](../task1/).

## 2. Methodology

**Endpoint:** `https://demo.dxfeed.com/webservice/rest/events.json`

**Instruments:**

| Instrument | Role | Candle symbol |
| ---------- | ---- | ------------- |
| AAPL | US large-cap equity | `AAPL{=1m}` (and 5m / 1h) |
| TSLA | High-volatility equity | `TSLA{=1m}` (and 5m / 1h) |
| EUR/USD | FX | `EUR/USD{=1m,price=bid}` (and 5m / 1h) |

Crypto (`BTC/USD`, `ETH/USD`) returned 0 candles on the demo feed, so TSLA was used for high volatility. Plain `EUR/USD{=1m}` returned no candle data; `price=bid` was required.

**Data window:** The request used timezone-less timestamps (`2026-09-17T09:30:00` to `2026-09-17T16:00:00`). The API returned data covering approximately 14:30–21:00 UTC, corresponding to 10:30–17:00 EDT on September 17, 2026. Therefore, the dataset does not represent the full 09:30–16:00 EDT regular trading session.
**Timeframes:** 1m, 5m, 1h  
**Artifacts:** [`task1/analyzer.py`](../task1/analyzer.py), [`task1/load_test.py`](../task1/load_test.py), CSVs in [`task1/data/`](../task1/data/)

**Aggregation rules used for comparison:**

| Field | Rule |
| ----- | ---- |
| open | first 1m open |
| high | max 1m high |
| low | min 1m low |
| close | last 1m close |
| volume | sum of 1m volumes |

##  3. Data Consistency & Integrity

### Scope and Methodology

Candle consistency was tested across three instruments representing different market behaviors:

| Instrument | Type                      | Symbol                   |
| ---------- | ------------------------- | ------------------------ |
| AAPL       | US equity                 | `AAPL{=1m}`              |
| TSLA       | High-volatility US equity | `TSLA{=1m}`              |
| EUR/USD    | FX                        | `EUR/USD{=1m,price=bid}` |

The request used timezone-less timestamps (`2026-09-17T09:30:00` to `2026-09-17T16:00:00`). The API returned data covering approximately 14:30–21:00 UTC, corresponding to 10:30–17:00 EDT on September 17, 2026. Therefore, the dataset does not represent the full 09:30–16:00 EDT regular trading session. Testing used 1-minute, 5-minute, and 1-hour candles.

The investigation:

1. Compared reported 5m candles against 1m aggregation.
2. Compared reported 1h candles against 5m aggregation.
3. Checked for missing, duplicate, and out-of-order timestamps.
4. Tested weekend and after-hours behavior.
5. Tested partial-candle behavior by varying `toTime`.
6. Tested quote freshness during market closure.
7. Tested timestamp behavior when timezone offsets were omitted.

OHLCV aggregation used:

```text
open   = first candle open
high   = maximum high
low    = minimum low
close  = last candle close
volume = sum of constituent volumes
```

### Confirmed Correct Behavior

* **0 OHLC integrity violations** across the compared instruments and timeframes.
* **No duplicate or out-of-order timestamps** were found.
* US equities returned **0 candles on weekends**.
* EUR/USD resumed around **Sunday 21:00 UTC**, consistent with the FX session reopening.
* After-hours gaps were consistent with **sparse/no-trade periods**, rather than evidence of feed corruption.

### Finding 1 — After-Hours Missing Intervals

| Instrument | Missing 1m intervals | Observation                                                       |
| ---------- | -------------------: | ----------------------------------------------------------------- |
| AAPL       |                    8 | Six 2-minute gaps and one 3-minute gap, all around 20:16–20:56 UTC (~16:16–16:56 EDT), after the 16:00 EDT regular-session close |
| TSLA       |                    4 | All occurred after the 16:00 EDT regular-session close            |
| EUR/USD    |                    0 | No missing intervals in the tested window                         |

**Interpretation:** After-hours trading can be sparse, so minutes with no trades may produce no candle. This is **not presented as a confirmed API defect**.

**Operational implication:** Clients that assume continuous 1-minute candles across after-hours periods must explicitly handle missing intervals.

### Finding 2 — AAPL Session-Boundary Volume Discrepancy

For the AAPL hourly candle **starting at 20:00 UTC (16:00 EDT)**:

* 5m aggregated volume: **10,337,956**
* Reported 1h volume: **10,531,811**
* Difference: **193,855 (~1.841%)**

The discrepancy was observed consistently in the tested data, but its cause was **not conclusively established**. Closing-auction behavior was considered as a hypothesis but could not be confirmed from the available evidence.

**Operational implication:** Clients relying on hourly candles for precise volume accounting should be aware that session-boundary volume may not exactly equal the sum of reported sub-hour volumes. Tick-level data or internal feed logs would be required for root-cause analysis.

### Finding 3 — Quote Timestamp Missing During Market Closure

On Saturday 2026-09-19, the AAPL quote response contained:

```text
bid=334.75  ask=334.88  time=None
```

The source of the retained bid/ask values could not be determined from the available evidence.

**Operational implication:** Without a quote timestamp, a client cannot programmatically establish quote freshness. This creates a potential silent-staleness risk during market closure.

### Finding 4 — Timezone Behavior Without Explicit Offset

In the tested requests, timestamps were timezone-less (no explicit offset). For the main candle request (`fromTime=2026-09-17T09:30:00` to `toTime=2026-09-17T16:00:00`), the API returned data covering approximately 14:30–21:00 UTC, corresponding to 10:30–17:00 EDT on September 17, 2026. This describes the API's actual behavior for the tested request, not an assumption about intended timezone semantics.

For example:

```text
fromTime=2026-09-17T10:00:00
```

returned data beginning at:

```text
15:00:00 UTC
```

which corresponds to **10:00 ET (UTC−5)** on the tested date.

This is an **empirical observation**, not a claim about a documented API-wide rule.

**Operational implication:** Clients should use explicit timezone offsets, preferably UTC, to avoid unintentionally querying the wrong time window.

### Finding 5 — Partial-Candle Suppression

When `toTime` falls inside an incomplete candle interval, the API returns the last **complete** candle rather than a partial candle.

For example, with `toTime=10:32 ET` for 5-minute candles:

* the last returned candle was **10:30 ET**;
* querying through `10:35 ET` returned the same 10:30 candle with higher volume/count.

This confirms that additional trades occurred during the remainder of the interval but were not included in the earlier request.

**Operational implication:** A client querying near the current time may receive data that appears behind the requested time by up to one candle interval. The response does not explicitly flag this suppression.

### Investigated and Retracted — Boundary Candle Hypothesis

An apparent boundary anomaly initially suggested that sequential queries might be double-counting a candle. Further investigation showed that candle timestamps represent **interval start times**, and the apparently duplicated 21:00 timestamp represented a new interval rather than the previous candle being included twice.

The hypothesis was therefore **retracted** and is documented as a methodological lesson rather than a confirmed defect.

### Additional Instrument Coverage Note

The assessment required an FX pair and a high-volatility instrument. Crypto was also investigated, but BTC/USD and ETH/USD returned **0 candles** from the demo environment. EUR/USD required the `price=bid` parameter to return candle data.

### Supporting Evidence

The detailed investigation, raw observations, methodology, and execution instructions are documented in [`task1/data_integrity.md`](../task1/data_integrity.md).


## 4. Real-Time Behavior Under Load

**Script / results:** [`task1/load_test.py`](../task1/load_test.py), [`task1/data/load_test_results.csv`](../task1/data/load_test_results.csv)

**Symbols:** AAPL, TSLA, MSFT, GOOG, AMZN, IBM, SPY  
**Window:** `2026-09-17T10:00:00` → `2026-09-17T10:10:00`  
**Levels:** 1, 5, 10, 20, 50 concurrent requests (50 requests per level)

### Main persisted run

| Concurrency | Success | Errors | Timeouts | HTTP 429 | p50 successful latency |
| ----------: | ------: | -----: | -------: | -------: | ---------------------: |
| 1 | 50/50 | 0 | 0 | 0 | ~601–603 ms |
| 5 | 50/50 | 0 | 0 | 0 | ~3.0 s |
| 10 | 50/50 | 0 | 0 | 0 | ~6.0 s |
| 20 | 50/50 | 0 | 0 | 0 | ~11.9 s |
| 50 | 25/50 | 25 | 25 | 0 | ~7.85 s† |

† Successful-request p50 at concurrency 50 is **survivor-biased** (failures/timeouts excluded).

Another run at concurrency 50 produced 16/50 successful (68% error), showing **run-to-run variability**.

### Interpretation

- Latency degrades substantially before outright failures (graceful through concurrency 20 in the main run)
- Failures/timeouts appeared at concurrency 50; the transition between 20 and 50 was not fully characterized
- No exact backend concurrency limit is claimed
- No HTTP 429s were observed; this does **not** prove rate limiting is absent
- Request timeout behavior was around 15 seconds in this client configuration; it should not be described as a perfect global deadline
- Matching response hashes on a fixed historical window do **not** prove caching
- All tested symbols showed the same general high-concurrency failure mode (timeouts)

### Proposed monitoring (illustrative, not official dxFeed policy)

p95/p99 latency · error rate · timeout rate · HTTP 429 rate · freshness / last-update lag · delayed/missing candle detection · per-symbol outliers · concurrency vs latency

Any SLO or escalation thresholds derived from this work are **proposed / illustrative only**.

Supporting write-up: [`task1/realtime_behavior_under_load.md`](../task1/realtime_behavior_under_load.md)

## 5. Operational Risk Review

| Risk | Observed signal | Detection focus | Mitigation focus |
| ---- | --------------- | --------------- | ---------------- |
| Data integrity | After-hours gaps; session-boundary volume mismatch | Interval completeness; independent volume checks | Explicit gap handling; secondary volume verification |
| Latency | p50 scales with concurrency before failures | p95/p99 + concurrency correlation | Client concurrency caps / backoff |
| Staleness | Missing quote `time`; fixed-`toTime` + partial suppression can look “frozen” | Freshness vs now; advancing `toTime` checks | Dynamic `toTime`; always-present timestamps |
| Silent failures | HTTP 200 with incomplete or non-advancing content | Count-vs-expected; content change over polls | Data-quality assertions beyond status codes |
| Monitoring blind spots | Availability-only checks miss rising latency and gaps | Layer transport + data-quality metrics | Do not treat HTTP 200 as data correctness |

Supporting write-up: [`task1/operational_risk_review.md`](../task1/operational_risk_review.md)

## 6. Incident Simulation

**Scenario (simulated, not a real production incident):** EUR/USD 5m candles appear frozen at 21:00 UTC while the market is active.

**Simulated explanation:**

1. Client continues using a fixed historical `toTime`
2. Client does not advance `toTime`
3. Partial-candle suppression causes every response to end on the same last complete candle

The API can be behaving correctly for the parameters given while the client perceives an outage.

Supporting write-up: [`task1/incident_simulation.md`](../task1/incident_simulation.md)

## 7. Product Improvements

Tied to observed behavior in three categories:

1. **Technical / API** — clearer timezone handling; optional metadata when a partial candle is omitted; always populate quote timestamps (including during market closure)
2. **Monitoring** — freshness, gap detection, timeout vs HTTP-error separation, concurrency-aware latency
3. **Documentation** — document empirical timezone defaults, partial-candle suppression, and after-hours gap expectations

Supporting write-up: [`task1/improvements.md`](../task1/improvements.md)

## 8. Limitations

- Crypto unavailable on the demo feed
- Partial-candle behavior was tested against historical data rather than during a live market session
- Hourly volume discrepancy was not traced to a definitive root cause
- Timezone behavior was observed empirically rather than confirmed from official documentation
- Load-test transition between concurrency 20 and 50 was not fully mapped; concurrency-50 rates varied between runs
- Fixed historical windows may introduce caching-like identical responses without proving a cache

## 9. Conclusion

Within the tested demo scope, candle OHLC consistency and timestamp ordering held. The material operational issues were integration and observability risks: after-hours gaps, an unexplained session-boundary volume mismatch, missing quote timestamps when the market is closed, ambiguous timezone defaults, partial-candle suppression that can look like staleness, and concurrency-driven latency/timeout degradation without observed 429s.

The most important support takeaway is that successful HTTP responses are not sufficient evidence of healthy market-data delivery; clients and monitors need explicit freshness, completeness, and parameter checks.
