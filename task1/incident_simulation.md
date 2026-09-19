# Incident Simulation — "Frozen" EUR/USD 5-Minute Candles

## 1. Incident Analysis

### What happened

A trading client reported that their EUR/USD 5-minute candle feed appeared to
stop updating at **21:00 UTC**, even though the FX market was still active
(EUR/USD trades nearly 24/5). The client's charting/analytics application
continued to display the same final candle well past 21:00 UTC, giving the
impression that data delivery had stalled.

### Timeline (illustrative)

| Time (UTC) | Event |
|---|---|
| 20:55 | Client's last few 5-minute candles update normally. |
| 21:00 | Client's application stops showing new candles; last displayed candle timestamp is ~21:00. |
| 21:00–23:40 | Client continues to observe the same "last" candle on every refresh; escalates to support believing the feed is dead. |
| 23:45 | Support engages Tier-1; ticket opened. |
| 00:10 (T+1) | Tier-1 reproduces the client's exact request and confirms the response also stops at the same timestamp. |
| 00:30 (T+1) | Tier-1 escalates to Tier-2/Engineering with reproduction evidence. |
| 01:15 (T+1) | Engineering inspects the client's request parameters and identifies a fixed `toTime`. |
| 01:30 (T+1) | Root cause confirmed; client notified with recommended fix. |

### Symptoms

* EUR/USD 5-minute candles stop advancing at a specific, fixed timestamp (21:00 UTC).
* No error responses were reported by the client — the API calls "succeed."
* The freeze point is exactly aligned with a round candle boundary.
* Other instruments/timeframes were not reported as affected (though this was not yet verified at symptom-report time).

### Initial hypotheses (unconfirmed at this stage)

1. **Hypothesis A:** The dxFeed demo feed itself has stopped publishing EUR/USD data (upstream outage).
2. **Hypothesis B:** A caching layer (CDN, proxy, or server-side cache) is serving a stale, frozen snapshot.
3. **Hypothesis C:** The client's request parameters are static/fixed and not being refreshed between calls.
4. **Hypothesis D:** The market data provider suppresses FX candles outside of a specific session window.

These were treated strictly as hypotheses until each could be checked against evidence. No hypothesis was communicated to the client as a root cause at this stage.

### Investigation steps

1. Requested the client's exact request URL/parameters (or a packet capture / application log of the API call) rather than relying on their description alone.
2. Replayed the client's exact request against the dxFeed demo REST API independently, from a clean environment, to separate "client-side rendering issue" from "API response issue."
3. Compared the response to the client's fixed request against a *new* request for the same symbol with an updated `toTime` (current time) to check whether fresh data was actually available from the API.
4. Checked the `toTime` value the client's application was sending across multiple calls made minutes apart.
5. Checked whether the last candle returned was a **complete** interval or a **partial** interval relative to the requested `toTime`.
6. Ruled out Hypothesis A (upstream outage) by confirming EUR/USD candles *were* available from the API for time ranges after 21:00 UTC when a correct, current `toTime` was supplied.
7. Ruled out Hypothesis B (caching) as the primary cause: identical results were returned consistently for the *client's exact parameters*, but different (fresh) results were returned immediately when `toTime` was advanced — indicating the API was responding correctly to the parameters given, not serving a stale cached response independent of input.
8. Ruled out Hypothesis D: EUR/USD is not subject to the session suppression pattern described; the behavior was reproducible purely by holding `toTime` fixed.

### Evidence

* Two consecutive replayed requests using the client's **unmodified, fixed** `toTime` returned identical candle sets, both ending at the same 21:00 UTC candle.
* A replayed request using the **same symbol** but an **updated, current** `toTime` returned additional, newer candles beyond 21:00 UTC — proving the upstream data was not frozen and the API was not globally malfunctioning.
* The last candle returned in the client's fixed-`toTime` response was a fully complete 5-minute interval; no partial/incomplete candle for the interval containing `toTime` was present in the response, consistent with partial-candle suppression at the requested boundary.
* The client's application logs (once obtained) showed the same literal `toTime` value being sent on every polling cycle, rather than a value derived from the current time.

### Root cause (confirmed)

The client's application was calling the API with a **hardcoded / non-advancing `toTime` parameter**. The API correctly and consistently returned all complete candles up to that fixed point in time — no more, no less. Because the API also does not return a partial/in-progress candle for the interval that straddles `toTime` (partial-candle suppression), the last candle in every response was the same complete 21:00 UTC candle, on every call. This is a **client-side integration defect**, not an API or upstream data outage.

### Why the data appeared frozen

From the client's point of view, every poll returned "new" JSON, but the *content* was identical because the query parameters were identical. The combination of (a) a fixed `toTime` and (b) the API's correct suppression of the incomplete trailing candle produced a response that looked, from the outside, exactly like a feed that had stopped updating — even though the underlying EUR/USD market data was flowing normally.

### Resolution

* Client was advised to compute `toTime` dynamically (e.g., current time, or omit `toTime` if the API supports an "up to now" mode) on each request rather than using a fixed value.
* Client confirmed that after updating their integration to advance `toTime`, candles resumed updating as expected.
* No API-side defect was identified; no engineering code change was required to restore the client's data flow.

---

## 2. Client Communication

**Subject: RE: EUR/USD 5-Minute Candle Feed — Investigation Result**

Hi [Client Name],

Thank you for reporting that your EUR/USD 5-minute candles appeared to stop
updating at 21:00 UTC. We understand how disruptive this looked given that
the FX market remained active, and we want to walk you through exactly what
we found.

**What we observed:** When we replayed the exact request your application
was sending, we consistently received the same candle data, always ending at
the 21:00 UTC candle — matching what you reported.

**What we investigated:** We compared your request against a request for the
same symbol using an updated, current time range, and confirmed that fresh
EUR/USD candle data beyond 21:00 UTC was in fact available from our API. We
also confirmed there was no gap or outage in the underlying market data.

**Confirmed root cause:** Your application's request to our API included a
`toTime` parameter that was fixed at a point corresponding to 21:00 UTC and
was not being advanced on subsequent calls. Our API is designed to return
complete data only up to the `toTime` you specify, and it intentionally does
not return an in-progress/incomplete candle for the interval that overlaps
your `toTime`. As a result, every call with that fixed `toTime` correctly
returned the same last complete candle — which, from your side, looked
identical to a frozen feed.

**What we recommend you change:** Please update your integration so that
`toTime` is computed dynamically at request time (e.g., the current time),
rather than being a fixed or cached value. If your use case is "give me
everything available up to now," we recommend refreshing `toTime` on every
poll cycle.

**Why this produced the behavior you saw:** Our API behaved correctly and
consistently for the parameters it was given; because those parameters
never changed, the response never changed either. This was not a data
outage or a defect in the feed itself.

We're glad we could track this down, and we're happy to review your polling
logic with you if that would help confirm the fix. Please let us know if
you have any further questions.

Best regards,
[Support Engineer Name]
dxFeed Technical Support

---

## 3. Internal Escalation Note (Tier-1 → Tier-2/Engineering)

**Ticket:** EUR/USD 5m candles reported "frozen" at 21:00 UTC
**Priority:** Medium — client-reported data issue, workaround/root cause identified
**Status:** Root cause confirmed; client-side fix communicated; no engineering action currently required

**Customer impact:** Client's charting/analytics application displayed stale
5-minute EUR/USD candles from 21:00 UTC onward, despite the market remaining
active. Client perceived this as a feed outage.

**Symptoms:** Repeated polling of the API by the client returned a response
that never advanced past the 21:00 UTC candle.

**Affected instrument/data:** EUR/USD, 5-minute candle (`Candle` event,
`{=5m}` period). Not yet reported for other symbols or timeframes.

**Investigation performed:**
- Replayed client's exact request parameters independently; reproduced the identical "stuck" response.
- Replayed the same symbol/timeframe with an updated `toTime`; confirmed fresh candles beyond 21:00 UTC were available, ruling out an upstream data outage.
- Confirmed the response for the fixed `toTime` contained only complete candles, with no partial candle for the interval overlapping `toTime`.
- Obtained client-side logs confirming the same literal `toTime` value was sent on every request.

**Evidence:**
- Two replays with the client's fixed `toTime`, minutes apart, returned byte-identical candle sets.
- One replay with an advanced `toTime` returned additional, newer candles for the same symbol.
- Client logs show a non-advancing `toTime` parameter across polling cycles.

**Confirmed root cause:** Client-side integration defect — `toTime` was not
being updated between requests. Combined with expected API partial-candle
suppression at the interval boundary, this produced a response that looked
frozen but was, in fact, correct given the input parameters.

**Current status:** Client has been informed of the root cause and the
required change (advance `toTime` dynamically). No API defect was found.

**Is engineering action required?** No code fix is required for this
incident. However, see the Post-Mortem for a documentation/monitoring
improvement recommendation to reduce the likelihood of recurrence and the
time-to-diagnose for similar future reports.

---

## 4. Post-Mortem Outline

### Incident summary
A client reported EUR/USD 5-minute candles appearing frozen starting at
21:00 UTC. Investigation confirmed the API was functioning correctly; the
client's integration was sending a fixed `toTime` parameter, and the API's
partial-candle suppression behavior made the resulting static response look
like a stalled feed.

### Root cause
Client-side: a hardcoded/non-advancing `toTime` parameter in the client's
polling logic, combined with the API's expected (but not clearly documented
to this client) behavior of omitting incomplete candles at the `toTime`
boundary.

### Contributing factors
- No client-side validation or alerting when `toTime` fails to advance between polling cycles.
- Partial-candle suppression at `toTime` is not prominently documented, making the resulting "last complete candle repeats forever" symptom non-obvious to integrators.
- No response metadata (e.g., a flag or field) that would let a client programmatically detect "you are querying a fully historical, closed window" versus "you are at the live edge of the data."

### Detection gap
Nothing in the API response distinguished "a valid, complete answer to a
now-stale request" from "the live edge of the data." The client had no
signal available to detect that their own `toTime` had stopped advancing
before they filed a report. Internally, there was also no proactive
monitoring that would have flagged a client's request pattern as using a
non-advancing time window.

### Customer impact
Perceived data outage for EUR/USD 5-minute candles for the client, from
21:00 UTC until the fix was applied on their end. No actual data or service
disruption occurred.

### Prevention
- Publish clear documentation of partial-candle suppression behavior at the `toTime` boundary (see related improvement proposal).
- Provide integration guidance / sample code demonstrating correct dynamic `toTime` usage for "latest data" polling use cases.

### Monitoring improvements
- Consider server-side/support-tooling detection of client request patterns that repeat an identical `toTime` (and/or identical full parameter set) across many consecutive polling cycles, to allow proactive outreach before the client notices a "frozen" feed.

### Documentation improvements
- Add an explicit, prominent note in the Candle/events API documentation explaining: (1) that `toTime` must be advanced by the caller to receive new data, and (2) that a candle interval overlapping `toTime` is omitted (not partially returned) until it is complete.

### Action items

| Action | Owner/Team |
|---|---|
| Add documentation section on `toTime` semantics and partial-candle suppression | Docs / API Product Team |
| Add integration example ("polling for latest candles") to developer docs | Developer Relations / Docs |
| Evaluate feasibility of a response indicator for "partial candle omitted" | Engineering — API Team |
| Evaluate feasibility of support-side monitoring for non-advancing client request patterns | Support Tooling / Engineering |
| Add this scenario to Tier-1 troubleshooting runbook as a known pattern | Support Enablement |
