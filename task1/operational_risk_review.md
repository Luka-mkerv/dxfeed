# Part 3 — Operational Risk Review

## Scope, method, and inputs

This review is built entirely from artifacts already produced in this
assessment. **No new HTTP requests were made** for this section:

- **Part 1** (`load_test.py` / `data/load_test_results.csv`) — transport-level
  load-test evidence (latency, errors, timeouts, 429s).
- **Part 1's `analyzer.py` and its already-fetched data** (`data/AAPL_1m.csv`,
  `AAPL_5m.csv`, `AAPL_1h.csv`, and the equivalent `TSLA_*`/`EUR_USD_*` files) —
  these were fetched by `analyzer.py` earlier in this assessment and were
  **re-analyzed, not re-fetched**, for this review. Specifically,
  `analyzer.py`'s own `aggregate_candles()`/`compare_candles()` functions were
  imported and run directly against the already-saved CSVs to reproduce its
  aggregation-consistency check without any additional network calls. This
  surfaced concrete evidence used below that had not previously been written
  up.
- **Part 2** (`realtime_behavior_under_load.md`) — concurrency/latency/error
  findings and their stated limitations.
- **Part 4** (`incident_simulation.md`) — the fixed-`toTime`/frozen-feed
  incident narrative. Part 4 is a **simulated scenario**, not a real customer
  ticket, and is used here only for its reasoning structure, not as
  independent empirical proof.
- **Part 5** (`improvements.md`) — the three confirmed findings (timezone
  ambiguity, partial-candle suppression, stale quote timestamps), used only
  as previously-stated findings, not re-verified independently in every case.

Throughout, evidence is labeled as **Observed** (directly measured in this
project's data), **Simulated/narrative** (from the Part 4 scenario), or
**Hypothesis** (a plausible but unconfirmed explanation). No official dxFeed
procedures, SLOs, or escalation policies are asserted anywhere below — all
such items are explicitly proposed operational practices.

---

## Risk summary table

| Risk | Evidence / observed behavior | Customer / operational impact | Detection strategy | Mitigation strategy | Escalation criteria |
|---|---|---|---|---|---|
| **Data integrity risk** | *Observed:* 1-minute data had 8 missing minutes for AAPL and 4 for TSLA, 0 for EUR/USD, in this single fetch. *Observed:* request used timezone-less timestamps (`2026-09-17T09:30:00` to `2026-09-17T16:00:00`); API returned approximately 14:30–21:00 UTC, corresponding to 10:30–17:00 EDT on September 17, 2026 — describing actual API behavior for the tested request, not an assumption about intended timezone semantics; therefore the dataset does not represent the full 09:30–16:00 EDT regular trading session. *Checked and retracted:* an earlier draft of this review flagged a "cross-granularity boundary inconsistency" (volume/count growing with candle-period coarseness at the `toTime` edge); on validation (see §1) this is fully explained by candles being start-time-labeled with differing durations, combined with a truncation artifact in this review's own comparison method — it is not demonstrably an API defect and is not carried forward as a risk. | Clients aggregating their own bars from tick/1‑minute data should not expect their reconstruction of the *very last* bucket in a truncated window to match the API's native coarser candle for that same window — not because of a demonstrated defect, but because a truncated finer-grained series is an incomplete basis for that specific comparison by construction. Clients can also misattribute a timezone-offset-driven time shift to a data problem. | Gap/interval-completeness checks per symbol; explicit timezone verification for boundary times. | Document the observed timezone-offset behavior for integrators. Separately, as a methodological precaution when validating aggregation logic across granularities (not a fix for a confirmed defect, since none was established): exclude the last (query-boundary) candle of a truncated finer series from that specific comparison, since a truncated series is an incomplete basis for it by construction. | Escalate if missing intervals or timezone-offset behavior reproduce consistently on independent, freshly-issued requests for the same symbol/window — not from a single occurrence. |
| **Latency risk** | *Observed (Part 2):* successful-request p50 scales almost exactly proportionally with concurrency for levels 1–20 (~600 ms per concurrency unit). *Observed:* at concurrency 50, failure rate was 50% in the persisted run (68% in an earlier run quoted in this assessment); 100% of failures were timeouts; 0 HTTP 429s at any level. | Clients issuing many parallel requests (e.g., scanning many symbols) will see rapidly growing latency well before any outright failure, and — if using long client-side timeouts — may perceive a "hang" rather than a clean error. | p95/p99 latency trend; timeout rate tracked separately from HTTP error rate (timeouts were the *only* failure mode observed); concurrency-vs-latency correlation. | Recommend client-side concurrency caps and backoff/retry for high-parallelism integrations; avoid unbounded per-symbol thread pools. | Sustained (not momentary) elevated timeout rate tied to a specific concurrency/volume pattern, reproducible independent of which symbols are requested. |
| **Staleness risk** | *Simulated/narrative (Part 4):* a fixed `toTime` plus partial-candle suppression can make a live, healthy feed look frozen. This is a constructed scenario, not independently reproduced empirically in this project (see §1 for a related boundary-candle check that was investigated and explicitly retracted as inconclusive). | A client can genuinely believe their feed is down and escalate, when the API is in fact returning exactly what was asked for. Misdiagnosis costs investigation time on both sides. | Compare latest returned candle timestamp against current time and the expected update cadence for that candle period; compare the client's actual `toTime` across successive polls to check whether it is advancing. | Ensure client integration uses a dynamically-advancing `toTime`; document partial-candle-suppression behavior; propose freshness monitoring (§ Monitoring metrics, Part 2). | Only after (a) request parameters are confirmed correct/dynamic and (b) the issue reproduces on a fresh, correctly-parameterized request — mirrors Part 4's own escalation note. |
| **Silent failure risk** | *Observed:* the missing 1-minute intervals (AAPL: 8 minutes; TSLA: 4 minutes) are invisible at the transport level — the request succeeds, the JSON is well-formed, and no gap indicator is present in the payload; only counting returned candles against the expected count reveals it. *Simulated:* the Part 4 frozen-feed scenario is, by definition, a "successful" API response that is nonetheless not what the client needed. | Neither `load_test.py` nor `analyzer.py`'s basic fetch treats these as failures — both only check HTTP status / JSON shape. A monitor built the same way would report full health while real data-quality issues exist underneath. | Combine transport checks (status, timeout, JSON shape — as Part 1 already does) with explicit data-quality checks: expected-vs-actual candle count for the requested window, freshness-vs-now. | Add data-quality assertions to client/integration layers, not just status-code checks (e.g., "did I receive the number of candles I expected for this window?"). | When data-quality checks fail consistently across repeated, correctly-parameterized requests — not on a single occurrence. |
| **Monitoring blind spots** | *Observed:* at concurrency 1–20, every request returned HTTP 200 while p50 latency grew ~20x — a pure uptime/status monitor would show 100% healthy throughout. *Observed:* the missing-interval issue above is also an HTTP-200, well-formed-JSON condition. *Simulated:* the Part 4 frozen feed is also HTTP-200 throughout its entire duration. | An operations team relying only on "is the endpoint returning 200s" gets a false sense of health during exactly the conditions this project found to be most informative (rising latency, missing intervals, frozen-looking-but-technically-correct responses). | See the per-risk detection strategies above; the common thread is that none of them are visible from status code / response time alone. | Layer data-quality and freshness checks on top of transport monitoring, per the metrics proposed in Part 2 §4. | N/A directly (this is a monitoring design gap, not an incident trigger by itself) — but its presence should be a standing rationale for adopting the detection strategies above before relying solely on uptime metrics. |

---

## 1. Data integrity risk (detailed)

### What was found

Re-running `analyzer.py`'s own `aggregate_candles()`/`compare_candles()`
logic against the already-saved 1-minute, 5-minute, and 1-hour CSVs for
AAPL, TSLA, and EUR/USD (fetched earlier in this assessment for the window
`2026-09-17T09:30:00`–`16:00:00`, no timezone specified) produced these
**observed** results:

- **A discrepancy at the very last timestamp in the requested window was
  investigated as a potential anomaly and retracted** (see "Validation and
  retraction" below): the evidence did not demonstrate a genuine
  data-integrity anomaly — only an expected consequence of start-time-labeled
  candles of differing durations, compounded by a truncation artifact in
  this review's own comparison method. That hypothesis is therefore
  retracted, not carried forward as a finding. Away from that boundary,
  1-minute data rolled up into 5-minute and hourly candles with no
  discrepancy, for all three instruments and both aggregation levels
  (1m→5m and 5m→1h) — a genuine positive finding: aggregation is otherwise
  self-consistent. The valid, retained finding from this check is the
  missing 1-minute intervals identified below.
- **Missing 1-minute intervals within the window** (real, from the raw
  `_1m.csv` files, independent of any aggregation logic): AAPL had 8 missing
  1-minute intervals — six 2-minute gaps account for 6 missing intervals and
  one 3-minute gap accounts for 2 missing intervals (6 + 2 = 8) — out of
  391 expected; TSLA had 4 missing minutes (four 2-minute gaps, each
  accounting for 1 missing interval); **EUR/USD had zero
  gaps** — every minute present. This is a real, symbol-specific difference
  observed in this one fetch; with only a single fetch per symbol, it should
  not be generalized into "equities are less complete than FX" as a general
  rule, only reported as what was actually observed here.
- **Timezone/offset behavior:** the request used timezone-less timestamps
  (`2026-09-17T09:30:00`–`2026-09-17T16:00:00`, matching standard NYSE
  market hours as written, per `analyzer.py`'s own comment "ET timezone
  implied by API"). The API returned data covering approximately
  `14:30`–`21:00` UTC, corresponding to `10:30`–`17:00` EDT on September
  17, 2026. Therefore, the dataset does not represent the full
  `09:30`–`16:00` EDT regular trading session. This describes the API's
  actual behavior for the tested request, not an assumption about intended
  timezone semantics. This directly reinforces the `improvements.md`
  Finding 1 (timezone ambiguity) with a concrete, measured example, though
  it does not by itself prove the internal mechanism. Timezone behavior
  was established empirically rather than confirmed from official
  documentation.

### Validation and retraction: "cross-granularity boundary inconsistency"

An earlier draft of this review flagged a "cross-granularity boundary
inconsistency" — the observation that, at the exact `toTime` boundary
(`2026-09-17 21:00:00 UTC`), the reported volume/count for the "same"
labeled timestamp grew with the coarseness of the requested candle period
(e.g. AAPL: 1m=253.86/19, 5m=814.71/56, 1h=193,844.33/1,037; the same
growth pattern held for TSLA and EUR/USD). Before treating this as a
data-integrity finding, it was checked directly against the raw CSVs and
against `analyzer.py`'s own logic. **This check shows the original framing
was not well-supported, and the claim is retracted as a data-integrity
risk.** The reasoning:

1. **Candle timestamps represent the candle's START time, not its end or
   midpoint.** This is directly demonstrated by the data, not assumed: the
   `20:55:00` 5-minute candle's volume (2,257.00) exactly equals the sum of
   the four available 1-minute candles at `20:55`, `20:56`, `20:58`,
   `20:59` (the `20:57` minute is one of the missing intervals noted
   above) — this arithmetic only works under a left-closed
   `[start, start+duration)` bucketing convention. Independently, the
   **open price at the `21:00:00` boundary is identical across the 1m, 5m,
   and 1h series for all three instruments** (e.g., AAPL: 336.72 in all
   three), which is exactly what you'd expect if all three candles begin
   at the same instant.
2. **Given start-time labeling, a candle timestamped `21:00:00` covers a
   different real-world interval at each granularity by construction:**
   1m → `[21:00:00, 21:01:00)`, 5m → `[21:00:00, 21:05:00)`, 1h →
   `[21:00:00, 22:00:00)`. A 5-minute and a 1-hour interval containing more
   trading activity than a 1-minute interval is the ordinary, expected
   consequence of covering more real time — not evidence of an
   inconsistency by itself.
3. **The magnitudes observed do not show unexplained inflation.** If
   anything, the boundary candles show *less* volume than a naive
   duration-based extrapolation would predict: AAPL's 5m boundary volume
   (814.71) is below a naive 5×253.86=1,269.3 extrapolation from the 1m
   rate, and the 1h boundary volume (193,844.33) is far below the
   preceding, unambiguously complete hour's volume (10,531,811.85). This
   is consistent with ordinary variable trading intensity (volume in this
   dataset already varies by an order of magnitude minute-to-minute), not
   with a mechanical defect inflating boundary candles.
4. **Whether the 5m/1h boundary candles used real tick data beyond
   `toTime=21:00:00` cannot be determined from this dataset.** The
   1-minute series itself was truncated at exactly that instant, so there
   is no ground truth in the already-fetched data for what, if anything,
   happened between `21:00` and `21:05` or between `21:00` and `22:00`.
5. **Critically, this project's own comparison method is expected to
   disagree with the API at exactly this boundary regardless of whether
   the API is behaving consistently.** `aggregate_candles()` can only sum
   whatever 1-minute rows are available; because the 1-minute series is
   truncated at `toTime`, its reconstruction of the final 5-minute (or
   1-hour) bucket necessarily uses only a fraction of the minutes a
   complete bucket would need. A mismatch between that incomplete
   reconstruction and the API's own native candle is the **expected
   result of the truncation**, not evidence of an API defect. Since "the
   API is inconsistent" and "this review's own reconstruction is
   incomplete at the truncation point" both predict the identical observed
   pattern — zero mismatches away from the boundary, all mismatches
   exactly at it — **the already-fetched CSV data cannot distinguish
   between these two explanations.**

**Conclusion:** this is not demonstrably anomalous and is not carried
forward as a data-integrity risk. The only actionable takeaway retained is
methodological, not a defect claim: when reconciling candles across
granularities from a bounded (`toTime`-limited) query, exclude the final
candle of the finer-grained series from the comparison, since it is an
incomplete basis for that specific check by construction.

### Detection / mitigation / escalation

- **Detect:** check raw interval counts against the expected count for the
  requested window and period (this is what actually found the missing
  1-minute intervals above); verify timezone-offset assumptions against a
  known reference (e.g., a date/time with an unambiguous, documented market
  event) rather than assuming ET conversion is DST-aware.
- **Mitigate (proposed):** document the observed timezone-offset behavior
  for integrators (ties directly to `improvements.md` Finding 1's proposed
  fix). Separately, as a methodological precaution for anyone re-running
  this kind of cross-granularity validation — not a fix for a confirmed
  product defect, since none was established — exclude the boundary candle
  of a truncated series from that specific comparison, since it is an
  incomplete basis for it by construction.
- **Escalate:** when missing intervals or timezone-offset behavior
  reproduce on an independent, freshly-issued request, across more than
  one symbol or instrument class (as observed here) — not from a single
  unverified customer report.

---

## 2. Latency risk (detailed)

Fully sourced from Part 2 (`realtime_behavior_under_load.md`); not
re-derived here, per the instruction not to modify or re-run that work.

- **Observed:** successful-request p50 latency rose from ~603 ms
  (concurrency 1) to ~11,939 ms (concurrency 20), a ~20x increase against a
  ~20x concurrency increase — an almost exactly proportional relationship
  (~600 ms per unit of concurrency, ±1%, at levels 1/5/10/20).
- **Observed:** at concurrency 50, failure rate jumped sharply (50% in the
  currently persisted run; 68% in an earlier run performed during this
  assessment) — a discontinuity relative to the 0% failure rate at every
  lower level tested. 100% of failures at concurrency 50 were client-side
  timeouts; none were HTTP error codes or 429s.
- **Observed:** zero HTTP 429 responses occurred at any tested concurrency
  level, in either logged run. Per Part 2, this does not establish that
  dxFeed's demo endpoint has no rate limiting — only that this test's
  specific pattern didn't trigger one.
- **Limitation (stated in Part 2, repeated here for risk framing):** no
  concurrency levels were tested between 20 and 50, so whether degradation
  is a gradual ramp or a sharp threshold in that range is unknown; this is a
  demo-endpoint benchmark and does not represent production capacity.

**Impact:** a client issuing many parallel requests (e.g., a dashboard
polling many symbols) could see latency grow substantially — and,
eventually, requests fail outright — well before any explicit rejection
(429) from the server. Because timeouts were the only observed failure
mode, clients with long or absent client-side timeouts may perceive this as
an application hang rather than a clear error condition.

**Detection / mitigation / escalation:** as summarized in the table above
and detailed further in Part 2 §4–§6 (proposed monitoring metrics, SLOs,
escalation triggers) — not repeated in full here to avoid duplicating that
section.

---

## 3. Staleness risk (detailed)

Sourced from the Part 4 incident simulation (`incident_simulation.md`),
which is a **constructed scenario for this assessment, not a real
customer incident**. It is used here for its investigative reasoning, not
as independent proof of production behavior.

- **Narrative mechanism:** a client requesting candles with a fixed,
  non-advancing `toTime` receives — correctly — the same complete data
  every time. Combined with the API's partial-candle suppression at the
  `toTime` boundary, the last candle returned never changes, which can look
  identical to a stalled feed even though the market and the underlying
  data are both active.
- **How a customer perceives valid behavior as an incident:** every
  individual response is technically correct for the parameters given, so
  there is no error to alert on; the "incident" only becomes visible when
  comparing *successive* responses over time, which most integrations
  (and most simple monitors) don't do by default.
- **Market-open vs. market-closed interpretation:** `improvements.md`
  Finding 3 notes that quotes may be returned without a timestamp during
  market closure, which would make staleness detection *even harder* in
  that scenario specifically — this is a documented finding carried over
  from Part 5, not independently re-tested in this review.

**Detection (proposed):** compare the latest candle's timestamp against
current time and the expected update cadence for that candle's period (a 5m
candle that hasn't advanced in >5 minutes during active market hours is a
freshness-check failure); separately, check whether the client-supplied
`toTime` itself is advancing across polls — a non-advancing `toTime`
combined with a "frozen" last candle is a strong, specific signal for the
Part 4 mechanism rather than a genuine feed outage.

**Mitigation (proposed):** ensure integrations compute `toTime` dynamically
(the Part 4 root-cause fix); document partial-candle-suppression behavior
so integrators don't need to rediscover it via a support ticket; add
freshness monitoring per Part 2's proposed metrics.

**Escalation:** only after (a) request/client-side parameters are
confirmed correct and dynamically advancing, and (b) the frozen/stale
behavior reproduces upstream on an independently-issued, correctly
parameterized request. This is a direct restatement of Part 4's own
escalation note, which explicitly warns against escalating an unverified
hypothesis as a confirmed root cause.

---

## 4. Silent failure risk (detailed)

This is the risk most directly demonstrated by this project's own tooling,
not just described abstractly:

- `load_test.py`'s `do_request()` treats a request as successful when the
  HTTP status is 2xx **and** the JSON body has the expected top-level shape
  (`status: "OK"` and a `Candle` key). It does not — and was never asked to
  — check whether the *data itself* is complete, fresh, or internally
  consistent.
- `analyzer.py`'s `fetch_candles()` similarly treats a 2xx response with a
  parseable candle array as success. It took a **separate, deliberate
  check** — counting returned rows against the expected count for the
  requested window — to discover the missing 1-minute intervals (AAPL: 8
  minutes; TSLA: 4 minutes) described in §1. The request that returned
  that data was a single successful HTTP 200 with well-formed JSON;
  nothing in the response signals that fewer candles were returned than
  the window should contain. This gap is completely invisible to a
  status-code-only check.
- The Part 4 frozen-feed scenario is, by construction, an HTTP 200 with a
  syntactically and semantically valid response for the parameters given —
  it is "wrong" only relative to the client's *intent*, not relative to the
  request actually sent.

**Principle:** HTTP 200 plus a well-formed response body indicates the
*transport and request handling* succeeded. It says nothing about whether
the returned data is complete (interval gaps), fresh (Part 4), or matches
what an integrator implicitly expected (Part 5 Finding 2/3). Detection must
therefore combine transport-level checks with explicit data-quality checks;
neither this project's load test nor its analyzer script did the latter
until an interval-completeness check was added specifically for this
review.

**Detection / mitigation / escalation:** as in the summary table — combine
status/shape checks with count-vs-expected and freshness checks; add
data-quality assertions to integration layers; escalate only on
consistent, repeated data-quality failures.

---

## 5. Monitoring blind spots (detailed)

Concretely, in this project, a monitor that only checked "did the endpoint
return HTTP 200 within N seconds" would have reported full health during
every one of the following **observed** conditions:

- **Rising latency with no failures (Part 2, concurrency 1→20):** every
  single request returned HTTP 200; only the latency distribution reveals
  the ~20x slowdown. A pure availability check has nothing to alert on
  here.
- **The missing 1-minute intervals (§1):** HTTP 200, valid JSON, correct
  schema — the absence is only visible by counting returned candles
  against the expected count for the window.
- **The Part 4 frozen-feed scenario:** HTTP 200 throughout its entire
  duration; only comparing the *content* of successive responses (or
  comparing the client's request parameters against current time) reveals
  the issue.
- **429 rate limiting specifically:** `load_test.py` had to add an explicit
  check for status code 429 separate from generic error handling — a
  monitor that only tracks "error rate" without breaking out 429 vs.
  timeout vs. other errors would not be able to distinguish rate-limiting
  from server-side failure or client-side timeout, even though this project
  found timeout to be the dominant (in fact, only) failure mode observed.

---

## Narrative: highest-value operational lessons

**HTTP 200 is necessary but not sufficient.** Every real finding in this
project — the missing intervals, the timezone offset, and the Part 4
frozen-feed mechanism — sits behind a technically successful HTTP response.
None of them would be caught by status-code-only monitoring. This is the
single thread connecting all five risk categories above, and it is the main
reason this review recommends layering explicit data-quality checks
(interval completeness, freshness-vs-now) on top of standard transport
monitoring, rather than treating request success as a proxy for data
correctness.

**Distinguish symptom from root cause before escalating — and be willing to
retract a hypothesis that doesn't hold up.** Part 4's investigation
explicitly modeled this discipline (replay the client's exact request;
compare against a corrected request; only then state a confirmed root
cause). This review applied the same standard to itself: an earlier draft
flagged a "cross-granularity boundary inconsistency" as a data-integrity
finding, but on direct validation against the raw CSVs (§1), it turned out
to be fully explained by ordinary start-time-labeled candle semantics plus
a truncation artifact in this review's own comparison method — not a
demonstrated API defect. It was retracted rather than kept as a hedged
"observed anomaly." The operational lesson for Tier 1/L2 is the same one
Part 4 demonstrates and this retraction reinforces: reproduce independently,
rule out mundane explanations (including flaws in your own analysis
method), and only escalate a confirmed — not a merely plausible-sounding —
root cause.

**Small-sample and single-run results should be treated as directional,
not definitive.** The missing-interval counts (§1) come from one fetch per
symbol; the concurrency=50 failure rate varied between two separate runs
performed during this assessment (50% vs. 68%); and several proposed
detection/mitigation ideas above are reasonable inferences from this data,
not validated production practices. None of this invalidates the findings —
each is real, measured, and reproducible from the saved artifacts — but the
review is scoped to the dxFeed **demo** endpoint under this project's
specific test conditions, and does not claim to represent production
behavior, official dxFeed policy, or backend architecture.
