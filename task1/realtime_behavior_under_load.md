# Part 2 — Real-Time Behavior Under Load

## Scope and data source

This section reuses the **existing Part 1 load-test implementation and results**
(`task1/load_test.py`, `task1/data/load_test_results.csv`). Per the assessment
instructions for this section, **no new benchmark run was performed** — all
analysis below is derived directly from the persisted CSV (250 request-level
rows: 5 concurrency levels × 50 requests, round-robin across the 7 symbols
AAPL, TSLA, MSFT, GOOG, AMZN, IBM, SPY, against the real dxFeed demo REST
endpoint). Part 1's script, methodology, and CSV are unchanged by this section.

The "burst traffic" required by Part 2 is exactly what the Part 1 load test
already generates: at each concurrency level, up to that many `{=1m}` Candle
requests for different symbols are in flight simultaneously via
`ThreadPoolExecutor`.

All figures below were recomputed directly from the current
`load_test_results.csv` to guarantee they match the persisted artifact.

## 1. Latency distribution, error rate, response consistency (measured)

| Concurrency | Requests | Success | Errors | Timeouts | 429 | Error % | Timeout % | p50 ms* | p95 ms* | p99 ms* |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1  | 50 | 50 | 0  | 0  | 0 | 0.0%  | 0.0%  | 603.0    | 1,392.5  | 1,435.1  |
| 5  | 50 | 50 | 0  | 0  | 0 | 0.0%  | 0.0%  | 3,001.5  | 3,224.6  | 3,420.2  |
| 10 | 50 | 50 | 0  | 0  | 0 | 0.0%  | 0.0%  | 6,005.8  | 6,162.7  | 6,227.2  |
| 20 | 50 | 50 | 0  | 0  | 0 | 0.0%  | 0.0%  | 11,938.7 | 12,163.8 | 12,165.8 |
| 50 | 50 | 25 | 25 | 25 | 0 | 50.0% | 50.0% | 7,845.9† | 14,195.8 | 14,742.1 |

\* Percentiles computed over **successful requests only** (Part 1 fix).
† Survivor-biased — see §4 "Is degradation graceful?" and "Does latency increase linearly?" below. Only 25/50 requests at concurrency 50 completed at all; the percentile reflects only that subset.

**Response consistency:** For every one of the 7 symbols, all successful
responses collected across the *entire* test (all concurrency levels, ~2.5
minutes of wall-clock time) shared exactly **one** distinct SHA-256 response
hash and exactly one distinct response size. In other words, 100% of
successful responses for a given symbol were byte-identical throughout the
test. This is expected given the query targets a **fixed, fully historical**
time window (`fromTime`/`toTime` both in the past); a closed historical
candle window should not change between requests. This is a stronger and
more mundane explanation than caching, and is called out explicitly so it is
not mistaken for a caching signal (see below).

**"Potentially cached" responses** (Part 1 definition: identical hash *and*
received within the same wall-clock second): **2 of 225 successful
responses (0.9%)**, both for AAPL. As established in Part 1, this is an
observation, not proof of caching — and given that *all* successful
responses per symbol were identical regardless of caching, the 0.9% figure
mainly reflects how often two requests for the same symbol happened to
complete within the same second, not how often the API "reused" a response.

## 2. Observed system behavior

### Rate limiting

**No HTTP 429 response was observed in any of the 250 requests**, at any
concurrency level (1, 5, 10, 20, or 50). The only failure mode observed at
any point in this test was the client-side request timeout (see below) —
zero HTTP 4xx/5xx status codes and zero 429s were recorded in the entire
dataset.

This does **not** establish that the dxFeed demo endpoint has no rate
limiting. It only means that this specific test — 7 symbols, a fixed
historical window, ≤250 total requests, ≤50 concurrent, over one run — did
not trigger one. A different request pattern, sustained duration, or
account/IP history could behave differently.

### Caching patterns

Covered above: response bodies were fully deterministic per symbol. No
data in this test can distinguish "the backend recomputed the same answer
every time" from "the backend served a cached answer every time" — both are
consistent with querying immutable historical data. No caching conclusion
is drawn.

### Stale data patterns

This benchmark used a **fixed** historical `fromTime`/`toTime` window by
design (per Part 1), so it does not exercise the live/streaming "is this
quote still updating" scenario at all. This is a genuine gap for Part 2's
"stale data patterns" ask: it cannot be answered from this dataset. (It is
addressed conceptually, not empirically, in Part 4's incident scenario,
where a fixed `toTime` combined with partial-candle suppression is shown to
*look* like frozen/stale data even when the API is behaving correctly.) A
proper empirical staleness test would require a separate run with a rolling
`toTime` (e.g., "now") during active market hours — not performed here, and
not part of the existing Part 1 artifact.

### Inconsistent symbol behavior

**Error/timeout by symbol (all concurrency levels combined):**

| Symbol | Requests | Success | Errors | Timeouts | 429 | Error % |
|---|---:|---:|---:|---:|---:|---:|
| AAPL | 40 | 35 | 5 | 5 | 0 | 12.5% |
| AMZN | 35 | 32 | 3 | 3 | 0 | 8.6%  |
| GOOG | 35 | 32 | 3 | 3 | 0 | 8.6%  |
| IBM  | 35 | 32 | 3 | 3 | 0 | 8.6%  |
| MSFT | 35 | 32 | 3 | 3 | 0 | 8.6%  |
| SPY  | 35 | 31 | 4 | 4 | 0 | 11.4% |
| TSLA | 35 | 31 | 4 | 4 | 0 | 11.4% |

AAPL shows 40 requests vs. 35 for the others — this is a deterministic
artifact of round-robin distribution of 50 requests over 7 symbols
(50 = 7×7 + 1, so the first symbol in the list gets one extra request per
concurrency level), not a symbol-specific behavior difference.

**Every failure, for every symbol, was the same error type: `timeout`.** No
symbol saw an HTTP error status, a connection error, a malformed/unexpected
response body, or a 429 that other symbols didn't also risk seeing. Cross-tabulating `error_type` by symbol shows only two values across the whole
dataset: `none` and `timeout`.

**All failures, for every symbol, were concentrated at concurrency=50** —
at concurrency 1, 5, 10, and 20, every symbol had 0 errors and 0 timeouts.
The per-symbol error percentages above are driven entirely by what happened
in the single concurrency=50 batch:

| Symbol | Requests @ c=50 | Success @ c=50 | Error % @ c=50 |
|---|---:|---:|---:|
| AAPL | 8 | 3 | 62.5% |
| AMZN | 7 | 4 | 42.9% |
| GOOG | 7 | 4 | 42.9% |
| IBM  | 7 | 4 | 42.9% |
| MSFT | 7 | 4 | 42.9% |
| SPY  | 7 | 3 | 57.1% |
| TSLA | 7 | 3 | 57.1% |

With only 7–8 requests per symbol at this level, one additional
success/failure shifts a symbol's rate by ~13–14 percentage points. A
42.9%–62.5% spread on this sample size is consistent with ordinary
randomness in which requests happened to be dispatched/queued fast enough
to finish inside the 15s window, not with a demonstrated symbol-specific
defect — especially since the failure *mode* (timeout only), response
*format*, and response *size stability* were identical across all 7
symbols.

**Latency by symbol at concurrency 1/5/10/20 (fully successful, no
censoring)** is tightly clustered, with no symbol standing out:

| Symbol | c=1 | c=5 | c=10 | c=20 |
|---|---:|---:|---:|---:|
| AAPL | 680 ms | 3,003 ms | 5,944 ms | 11,933 ms |
| AMZN | 761 ms | 3,000 ms | 6,003 ms | 12,009 ms |
| GOOG | 556 ms | 3,005 ms | 6,009 ms | 12,008 ms |
| IBM  | 589 ms | 3,001 ms | 6,006 ms | 11,852 ms |
| MSFT | 754 ms | 3,003 ms | 6,006 ms | 12,011 ms |
| SPY  | 605 ms | 3,004 ms | 6,003 ms | 12,007 ms |
| TSLA | 600 ms | 2,996 ms | 6,008 ms | 12,158 ms |

At concurrency=50, per-symbol medians range more widely (4,086 ms – 9,636
ms), but each is based on only 3–4 successful samples — too few to treat as
a reliable per-symbol latency signal; this spread is attributed to the same
small-sample effect noted above, not to a symbol-specific slowdown.

**Response sizes** differ slightly by symbol (3,588–3,655 bytes) but are
*perfectly constant* for a given symbol across the whole test — consistent
with symbol-specific numeric formatting (different digit counts in
price/volume fields) for otherwise identical fixed-window candle data, not
an anomaly.

**Conclusion:** No material, statistically distinguishable symbol-specific
inconsistency was observed. All 7 symbols showed the same failure mode
(timeout only, no 429/HTTP-error/connection-error variation), 0% failures
at concurrency ≤20, comparable latency at concurrency ≤20, and per-symbol
byte-identical successful responses throughout. The error-rate spread at
concurrency=50 is attributable to small per-symbol sample size at that
level, not to a demonstrated per-symbol defect.

## 3. Answering the four behavioral questions

### What fails first?

**Timeouts fail first — and, within this test, exclusively.** No errors of
any kind occurred at concurrency 1, 5, 10, or 20. At concurrency 50, all 25
failed requests were client-side timeouts (exceeded the 15s request
timeout); zero were HTTP 4xx/5xx status codes, zero were connection errors,
zero were malformed responses, and zero were HTTP 429. In this test, the
system's load ceiling manifested as *the client giving up waiting*, not as
an explicit rejection from the server. As above, this does not prove 429
rate limiting doesn't exist elsewhere in dxFeed's infrastructure — only that
it wasn't triggered by this specific request pattern.

### What degrades first?

**Latency degrades first, well before any failures appear.** From
concurrency 1 to 20 — all with 100% success — successful-request p50 rose
from ~603 ms to ~11,939 ms with zero failures. Only at concurrency 50 do
outright failures appear. Moreover, the latency increase from 1→20 is
almost exactly *proportional* to the concurrency increase:

| Concurrency | p50 | p50 ÷ concurrency |
|---:|---:|---:|
| 1  | 603.0 ms    | 603.0 |
| 5  | 3,001.5 ms  | 600.3 |
| 10 | 6,005.8 ms  | 600.6 |
| 20 | 11,938.7 ms | 596.9 |

The ratio is essentially constant (~600 ms per unit of concurrency, within
~1%). Extrapolating that same ratio to concurrency 50 predicts a ~30,010 ms
median latency — nearly double the 15,000 ms request timeout. This is
directly consistent with (though does not by itself prove a specific
backend mechanism for) why a large share of concurrency=50 requests timed
out: if the underlying per-request service time at that load level is
genuinely around 30s, any request that doesn't get an unusually fast queue
position will exceed the 15s client timeout before completing.

### Is degradation graceful?

**Graceful through concurrency 20; not graceful at concurrency 50, within
the levels actually tested.** Up to concurrency 20, degradation is graceful
in a specific, narrow sense: 100% of requests still complete successfully —
only more slowly. No requests are dropped or failed. At concurrency 50, this
changes sharply: success rate falls from 100% to 50% and the error/timeout
rate jumps from 0% to 50% in the same step. That is a discontinuous change
in failure rate between the levels tested, not a smooth, gradually rising
failure rate. Because the test only covers 1, 5, 10, 20, and 50 — with no
intermediate points between 20 and 50 — **it is not possible to determine
from this dataset whether the underlying transition is a gradual ramp or a
sharp threshold somewhere between concurrency 20 and 50.** The honest,
data-supported statement is: degradation was graceful (latency-only) at
every level actually tested below 50, and was abrupt (majority failures) at
the one level tested at 50 — the shape of the transition in between is
unknown.

*(Note on run-to-run variability: an earlier run performed during this
assessment — cited in this task's own prompt as a "representative result,"
but not the run persisted in the current CSV — recorded 16/50 successful
and a 68% error rate at concurrency 50, versus 25/50 successful and 50% in
the currently persisted run. Both runs agree that failures are concentrated
at concurrency 50 and are dominated by timeouts, but the exact failure rate
differed between runs. This indicates the concurrency=50 result is
sensitive to run-to-run conditions of the shared, external demo endpoint,
not a fixed, precisely reproducible threshold — reinforcing that the
20→50 transition shape should not be over-interpreted from a single run.)*

### Does latency increase linearly or exponentially?

**Linearly (proportionally), within the range that can actually be
measured — indeterminate at concurrency 50.** At concurrency 1, 5, 10, and
20 — all fully successful, with no censoring — the p50-to-concurrency ratio
is nearly constant (~600 ms ± 1%, table above), which is the signature of a
linear/proportional relationship, not an exponential one (an exponential
relationship would show that ratio itself growing sharply with
concurrency). The concurrency=50 data point **cannot** be used to test this
relationship: its successful-only p50 (7,845.9 ms) sits far *below* what the
linear trend predicts (~30,010 ms), but this is because timeouts remove the
slowest half of requests from the percentile calculation (survivorship
bias) — a measurement artifact, not evidence that scaling became sub-linear
or plateaued. **Conclusion: latency increases approximately linearly with
concurrency for levels 1–20; the relationship at concurrency 50 is
indeterminate from this dataset and should not be classified as linear,
exponential, or sub-linear from the successful-only figure alone.**

## 4. Proposed monitoring metrics

*These are proposed operational monitoring metrics based on the behavior
observed above. They are not official dxFeed monitoring standards — no such
document was inspected or is claimed to exist.*

| Metric | Why (tied to observed behavior) |
|---|---|
| p95/p99 latency, per symbol/endpoint | Latency rose smoothly and predictably before any failures occurred; tracking the upper-percentile trend can give advance warning before it crosses the timeout threshold. |
| Error rate (all non-2xx / failed requests) | The clearest, least-biased indicator of degradation — unlike successful-only latency, it captures every request that never completed. |
| Timeout rate, tracked separately from HTTP error rate | In this test, timeouts were the *only* failure mode observed; distinguishing "client gave up waiting" from "server explicitly rejected" is operationally important since they imply different root causes. |
| HTTP 429 rate | None were observed here, but that doesn't mean 429s can't occur under other conditions; this should still be tracked continuously, not assumed absent. |
| Data freshness / last-update timestamp lag | Not exercised by this benchmark (fixed historical window), but directly relevant to the live-data staleness gap noted above and to the Part 4 incident scenario. |
| Delayed or missing candle detection | Complements freshness monitoring; would catch partial-candle-suppression-style gaps (Part 4/5) proactively rather than via customer report. |
| Per-symbol failure rate / outlier detection | This benchmark found no material per-symbol difference, but with only 7–8 samples per symbol at the highest load level, a real per-symbol issue could easily have been missed; production monitoring should track this per-symbol, not just in aggregate. |
| Concurrent in-flight request count vs. observed latency/error rate | Directly mirrors this benchmark's independent variable; correlating live concurrency with latency/error trends would let operations see a version of the linear-latency relationship found here in real time. |

## 5. Proposed SLO definitions

*The measurements in §1–3 above are empirical results from this specific
benchmark. The SLOs below are proposed operational recommendations and
illustrative examples only — they are not derived from, and do not
represent, any official dxFeed SLA/SLO target. Any numeric thresholds are
labeled illustrative and would need to be set by dxFeed based on actual
production capacity planning, not this demo-endpoint benchmark.*

- **Availability / success rate (illustrative):** e.g., "≥99% of requests
  complete successfully (non-timeout, non-5xx, valid response body) within
  a defined normal operating load." The 0% error rate observed at
  concurrency ≤20 in this test is *consistent* with such a target being
  achievable under comparable load, but this benchmark targeted the demo
  endpoint only and cannot establish a production capacity figure.
- **Latency SLO (illustrative):** e.g., "p95 latency ≤ N seconds under
  defined normal load." This benchmark cannot propose a specific N for
  production, since latency here was shown to scale with concurrency in a
  way that is specific to this demo endpoint under this test's conditions.
  What it does support is the *structure* of such an SLO: track p95/p99,
  not just p50, since this test's p95/p99 diverged further from p50 as
  concurrency rose.
- **Market-data freshness SLO (illustrative):** e.g., "quote/candle data
  reflects the market no more than M seconds behind real time during active
  market hours." This dimension was not tested empirically here (fixed
  historical window only) and is included because it is directly relevant
  to the Part 4 incident and Part 5 Finding 2/3 — but no measurement from
  this benchmark supports a specific M.

## 6. Proposed escalation triggers (Tier 1 → Tier 2/Engineering)

*General, proposed operational criteria based on this analysis — not
confirmed official dxFeed escalation policy; no such policy document was
inspected or is claimed to exist.*

- Sustained elevated error or timeout rate over a defined window (this
  benchmark shows failure rate can move from 0% to >50% between two tested
  load levels — a sustained, not momentary, elevation is a reasonable
  escalation signal, given the run-to-run variability noted above).
- Repeated HTTP 429 responses (none were observed in this benchmark, but a
  sustained pattern of them in production is a distinct signal from the
  timeout-dominated behavior seen here and should be escalated separately).
- Market-data freshness/staleness exceeding an agreed threshold (see Part 4
  incident — this can also be a false alarm caused by a client-side fixed
  `toTime`, so escalation criteria should require confirming the request
  parameters first, per the Part 4 investigation steps).
- Multiple symbols affected simultaneously with the *same* failure mode
  (this benchmark's symbol analysis found no per-symbol divergence in
  failure type — a real incident where different symbols suddenly show
  different failure modes, or where previously-unaffected symbols start
  failing together, is a stronger signal than an isolated single-symbol
  report).
- Issue is reproducible with a verified, valid request (i.e., parameters
  independently re-checked against documented API usage) — mirrors the
  Part 4 investigation approach of replaying the client's exact request
  before escalating.
- Issue persists after client/request parameters (timezone, `toTime`,
  symbol/candle notation) have been verified correct — escalate only once
  client-side causes (as in Part 4) have been ruled out.
- Significant customer impact (trading decisions affected, multiple
  clients reporting, or a client-facing SLA at risk) — impact should be
  assessed independently of whether the root cause is yet known, per the
  Part 4 escalation note's distinction between "confirmed customer impact"
  and "confirmed root cause."

## 7. Known gaps in this analysis

- **Staleness/live-data behavior was not empirically tested** — the Part 1
  benchmark uses a fixed historical window by design, so no rolling-`toTime`
  or live-market staleness measurement exists in this dataset.
- **No intermediate concurrency levels between 20 and 50** were tested, so
  the shape of the degradation transition in that range is unknown.
- **Single run persisted per concurrency level** — no repeated trials at
  the same level, so within-level variance (as opposed to the observed
  run-to-run variance at concurrency 50 across separate executions) is not
  characterized.
- **Small per-symbol sample sizes at concurrency 50** (7–8 requests per
  symbol) limit confidence in any per-symbol comparison at that level.
- **Single test origin/network path** — no distributed or multi-region
  testing was performed.
