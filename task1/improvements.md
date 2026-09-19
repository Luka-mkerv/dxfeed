# Product Improvement Proposals

These proposals are based strictly on the three confirmed findings supplied
for this assessment. No additional statistics, customer counts, or
undocumented API behaviors are asserted beyond what is described below.

---

## Improvement 1 — Explicit Timezone Documentation and Parameter

### Problem

In tested requests, timestamps without an explicit timezone offset behaved
consistently with Eastern Time (ET) for parameters such as `fromTime`/`toTime`.
This was observed empirically against the demo endpoint and was not confirmed
as an official API-wide documented rule. The default is also not clearly
surfaced as a warning in the request/response cycle. An
integrator supplying a timestamp without a timezone (a very natural thing to
do) will silently have it interpreted as ET. If the integrator assumed UTC,
local time, or another exchange's timezone, every query will be
systematically offset with no error or indication that a default was
applied.

**Operational consequence:** Silent misalignment of requested vs. intended
time windows. This can cause candles to appear at the "wrong" time, data to
seem missing or duplicated near market open/close, or — as in incident
scenarios like frozen-looking feeds — additional confusion when diagnosing
time-window issues, because the assumed timezone is not obvious from the
request or response alone.

### Proposed Solution

1. Support an explicit, optional timezone qualifier on time parameters (e.g.
   an offset or IANA timezone suffix on `fromTime`/`toTime`, or a separate
   `timezone` parameter), so integrators who need UTC or another timezone
   are not forced to rely on an undocumented default.
2. Regardless of whether the parameter is added, document the ET default
   explicitly and prominently in the API reference for every endpoint that
   accepts time parameters, including a worked example showing the same
   instant expressed in ET vs. UTC.
3. Optionally, echo the timezone actually used for interpretation back in
   the response metadata, so a client can verify their request was
   interpreted as intended without needing to consult documentation each
   time.

### Estimated Complexity

**Low.** Adding documentation and a response echo of the assumed timezone
is a low-risk, low-effort change. Adding an optional explicit timezone
parameter is a moderate addition to request parsing, but can be implemented
additively (backward compatible with the existing ET default) without
touching core candle/event computation logic. The overall proposal is rated
Low because the highest-value, lowest-risk components (documentation, and
echoing the interpreted timezone) require no behavioral changes at all.

### Business Impact

- **Who is affected:** Any integrator or client application constructing
  time-range queries, particularly those newly integrating with the API or
  operating primarily in UTC or a non-US timezone.
- **How they are affected:** They may receive data for the wrong time
  window without any error, leading to incorrect analytics, misaligned
  backtests, or apparent data gaps that are actually just timezone
  offsets.
- **Operational/customer benefit:** Reduces a class of silent,
  hard-to-diagnose integration bugs; reduces support ticket volume related
  to "missing" or "misaligned" data; improves first-time integration
  success and trust in the API's correctness.

---

## Improvement 2 — Explicit Signaling of Partial-Candle Suppression

### Problem

When `toTime` falls in the middle of a candle interval, the API silently
omits the incomplete candle rather than returning it (even marked as
partial) or explicitly indicating that suppression occurred. From the
client's perspective, a response that ends exactly at the last *complete*
candle is indistinguishable from a response that ends there because no
newer data exists yet, or because the feed has stopped updating.

**Operational consequence:** As demonstrated in the incident simulation,
this ambiguity can make a correctly functioning feed appear "frozen" to a
client whose `toTime` is not advancing, and more generally makes it harder
for any client to distinguish "you're caught up to the live edge" from "your
query window is stale."

### Proposed Solution

Add an explicit indicator to the response when partial-candle suppression
has occurred for a given symbol/interval — for example, a metadata field
alongside the candle data (e.g. `"partialCandleOmitted": true` with the
boundary timestamp) whenever the requested `toTime` falls strictly inside an
otherwise-incomplete interval. This requires no change to the returned
candle set itself (complete candles are still the correct data to return),
only an additive, backward-compatible metadata signal that lets clients
programmatically detect the suppression condition instead of inferring it
indirectly.

### Estimated Complexity

**Medium.** The suppression logic already exists internally (the API must
already determine which candle would be incomplete in order to omit it), so
the primary work is exposing that existing determination in the response
schema and ensuring it is populated consistently across all candle
endpoints/periods. Complexity is Medium rather than Low because it touches
the response schema (requiring careful backward-compatibility handling for
existing consumers) and needs to be verified across all supported candle
periods (1m, 5m, 1h, etc.).

### Business Impact

- **Who is affected:** Any client polling for "latest" candle data,
  especially those building live/near-real-time dashboards or automated
  trading logic that depends on knowing whether they are current.
- **How they are affected:** Without this signal, clients cannot
  distinguish a legitimately stale query window from a live feed that has
  no newer complete data yet, increasing the risk of misinterpreting data
  as frozen, delayed, or missing.
- **Operational/customer benefit:** Faster, more confident self-diagnosis
  by clients (reducing dependence on support escalations like the one in
  this assessment's incident scenario), and enables clients to build more
  robust polling logic that reacts correctly to the live edge of available
  data.

---

## Improvement 3 — Reliable Staleness Indication for Quotes During Market Closure

### Problem

During market closure, quotes may be returned without a timestamp, making
it difficult for a client to determine how stale a given quote is. Without a
reliable timestamp, a client cannot distinguish a quote that reflects the
most recent pre-close activity from one that is otherwise indeterminate in
age, which is particularly important for risk, compliance, and display
use cases that must avoid presenting stale prices as current.

**Operational consequence:** Client applications that display or act on
quote data may be unable to correctly flag stale/closed-market quotes to
end users, or may need to build ad hoc heuristics (e.g., checking market
hours themselves) to compensate for the missing timestamp.

### Proposed Solution

Ensure quote responses always include a timestamp field, even during market
closure — populated with the timestamp of the last actual quote update
(rather than omitted) — and additionally include an explicit status
indicator (e.g. `"marketState": "closed"` or `"stale": true`) so clients do
not have to infer market state indirectly. This is additive to the existing
response schema and does not change the underlying quote values returned.

### Estimated Complexity

**Medium.** The underlying last-known quote and its timestamp should
already exist internally (since it's what's being returned), so the primary
work is ensuring the timestamp field is always populated rather than
omitted, plus adding a market-state/staleness indicator. Complexity is
Medium because it may require coordinating behavior across multiple
event/data sources and instrument types (equities vs. FX, which have
different closure schedules), and requires care to avoid breaking existing
clients that may treat a missing timestamp as a meaningful signal today.

### Business Impact

- **Who is affected:** Clients consuming quote data outside of active
  market hours, including dashboards, risk systems, and any downstream
  process that needs to know how current a displayed price is.
- **How they are affected:** Without a reliable timestamp, they cannot
  programmatically determine quote staleness and risk presenting or acting
  on outdated prices as if they were current.
- **Operational/customer benefit:** Enables clients to reliably flag stale
  quotes in their own UIs and downstream logic, reducing the risk of
  displaying or acting on outdated market data during closed-market
  periods, and reducing the need for clients to independently reconstruct
  market-hours logic to compensate for the missing timestamp.
