# Task 2 — API Incident Investigation

## 1. Objective

Perform a scenario-based investigation of an API reliability incident: determine scope and impact, evaluate the evidence, form testable hypotheses, decide when to escalate, and propose preventive improvements.

This is not a real production incident. The actions below describe what an investigator **would** do.

## 2. Incident Summary

At **14:02**:

| Signal | Observation | Interpretation |
| --- | --- | --- |
| API error rate | 0.2% → 7% | About 35× baseline; distribution by endpoint, instance, and customer is unknown |
| CPU | ~95% on 2 of 5 instances | Could be a cause, consequence, or unrelated symptom |
| Deployments | None in the previous 24 hours | Makes a recent code release less likely, but does not exclude configuration, infrastructure, or scheduled changes |
| Traffic | Normal | Makes a traffic spike unlikely |
| Customer report | One enterprise customer reporting intermittent 502s | Confirms customer impact; other customers may also be affected |

## 3. Initial Scope and Impact

**Known:**

- The aggregate API error rate is elevated.
- Two of five instances have high CPU.
- At least one enterprise customer is affected on `/api/orders`.
- `/api/health` returns 200 in about 8 ms.

**Unknown and to confirm first:**

- Is the 7% error rate global or concentrated by endpoint, instance, customer, or region?
- Are the 502s concentrated on the two high-CPU instances?
- Are other endpoints affected?
- Are order write operations affected, or only reads?

These questions determine urgency and which mitigations are safe. For example, draining two instances may help an instance-local problem, but could overload the remaining instances if the bottleneck is shared.

The successful health check only shows that the endpoint is responsive. It does **not** show that the API or its downstream dependencies are healthy.

## 4. Evidence Assessment

```text
14:01:58 GET /api/orders 200 120ms
14:02:01 GET /api/orders 502 5320ms upstream timeout
14:02:03 WARN retrying request to internal-service
14:02:05 ERROR upstream request failed: context deadline exceeded
14:02:07 GET /api/orders 502 5101ms upstream timeout
14:02:10 INFO connection pool size: 100 active: 100 idle: 0
14:02:11 WARN slow query detected: 4800ms
14:02:15 GET /api/health 200 8ms
14:02:20 ERROR upstream request failed: context deadline exceeded
```

| Observation | What it indicates | Limitation |
| --- | --- | --- |
| `/api/orders` returns 502 after about 5 seconds | The API waits for an upstream dependency and reaches a timeout | Does not identify where the time is spent |
| `context deadline exceeded` | Upstream work exceeded its deadline | Could involve connection waiting, query execution, or processing in `internal-service` |
| Retry warning | The application retries a call to `internal-service` | This is not a client retry; retry count and backoff policy are unknown |
| Pool at 100 active / 0 idle | The logged connection pool was saturated at that moment | The log does not identify which pool or prove when saturation began |
| Slow query at 4.8 seconds | At least one database operation was slow | The query could be the cause or a result of wider contention |
| `/api/health` returns 200 | The health endpoint remains responsive | It does not test the complete business path |

## 5. Hypotheses

| Hypothesis | Supporting evidence | How I would test it |
| --- | --- | --- |
| **H1 — Slow database work is holding connections, saturating the pool, and causing timeouts** | Slow query, saturated pool, and upstream deadlines | Compare connection-acquisition wait with query-execution time; inspect active queries, locks, query plans, and DB resource use |
| **H2 — Pool saturation has another cause, such as a connection leak or slow processing in `internal-service`** | Same pool and timeout evidence; CPU is high on two instances | Check connection lifetime, pool usage, thread state, garbage collection, and service processing time |
| **H3 — The two high-CPU instances are independently degraded** | CPU is ~95% on 2 of 5 instances | Determine whether errors are concentrated on those instances and whether CPU rose before the errors |
| **H4 — Retries are amplifying the incident** | Retry warnings occur during degradation | Measure retry volume, attempts per request, and correlation with pool pressure |

H1 is the leading hypothesis because it best fits the available evidence, but it is **not a confirmed root cause**. Connection-wait and database-side telemetry are required to verify it.

## 6. Working Failure Model

A plausible, unconfirmed sequence is:

1. Database or other downstream work slows.
2. Connections remain active longer and the pool fills.
3. New requests wait and exceed their deadlines, producing 502s.
4. Application retries add load to an already degraded dependency.
5. CPU rises on some instances as a contributor or consequence.

The onset near 14:02 also makes scheduled activity worth checking: batch jobs, backups, maintenance, cache expiry, or statistics updates. This is another hypothesis, not an observed fact.

## 7. Investigation and Mitigation Plan

### Investigation order

1. **Confirm scope:** break errors down by endpoint, instance, customer, and region. This establishes customer impact and whether the issue is local or shared.
2. **Build a timeline:** correlate errors, latency, per-instance CPU, pool utilisation, database latency, and retries from before and after 14:02. This shows which signal changed first.
3. **Review changes:** check configuration, feature flags, scheduled jobs, database maintenance, infrastructure events, and recent data growth. No deployments does not eliminate these triggers.
4. **Inspect the dependency path:** examine connection-acquisition wait, query-execution time, active sessions, locks, long-running queries, and database CPU/I/O.
5. **Measure retries:** confirm retry count, backoff, and whether retries apply to non-idempotent order operations.
6. **Investigate CPU:** identify the process and workload consuming CPU and determine whether the increase preceded or followed the errors.

### Possible mitigations

| Action | When it may help | Risk |
| --- | --- | --- |
| Drain the two high-CPU instances | Errors are concentrated on them | Remaining instances may become overloaded |
| Reduce retries or add backoff | Retries are materially amplifying load | Requires a safe, reversible configuration change |
| Stop a confirmed problematic query | A specific query or lock is driving contention | Requires DBA review and may remove diagnostic evidence |
| Scale out | Capacity is limited at the API tier | Could increase connection pressure on a shared database |

Mitigation should follow evidence. Blindly scaling or restarting instances could worsen the incident or hide its cause.

## 8. Escalation Decision

**Decision: escalate. Thirty minutes is the latest escalation point, not the first communication.**

At 30 minutes, the error rate remains at 5–8%, customer impact continues, and there is no demonstrated recovery. The leading hypothesis also requires database and application-level access that a support engineer may not have.

Operational timeline:

- **T+0–5:** acknowledge the incident, begin scoping, and open an incident channel.
- **T+10–15:** update the support lead or account team and give the backend/DB owners an early warning.
- **T+15–20:** attempt evidence-based, reversible mitigations.
- **T+30:** formally escalate if the incident remains unresolved.

I would escalate immediately if errors were increasing, more customers or services became affected, order writes were failing, data integrity was at risk, or an SLA threshold was approaching.

Escalation is not a hand-off. I would continue investigating and managing customer communication in parallel.

**Escalation targets:**

- Senior backend/application engineer
- DBA or database platform team
- Incident commander if severity or SLA criteria require it

**Escalation package:**

- Error rate, duration, affected endpoints, instances, and customers
- Customer-visible symptoms and order write-path status
- CPU, latency, traffic, pool, slow-query, and retry evidence
- Actions attempted and their results
- Leading hypothesis clearly labelled as unconfirmed
- Specific requests for database, application, and infrastructure owners

## 9. Preventive Improvements

### 1. Connection-Pool and Dependency-Latency Monitoring

**Problem:** Pool saturation was visible only when it reached 100 active connections. The health endpoint did not expose degradation on the business path.

**Solution:** Export per-instance metrics for active, idle, and waiting connections plus acquisition-wait time. Alert at approximately 70–80% sustained utilisation, with a critical alert before full exhaustion. Also alert on abnormal connection-wait and query latency.

**Why it helps here:** It would detect rising pressure before the pool reached 100/100 and help distinguish waiting for a connection from executing a slow query.

**Complexity:** Low  
**Business impact:** Earlier detection, shorter customer-impact window, and fewer SLA breaches.

### 2. Circuit Breaker and Controlled Retries

**Problem:** Application-level retries may add load while `internal-service` is already degraded. Retrying non-idempotent order writes could also create duplicate-operation risk.

**Solution:** Use a circuit breaker with a small retry budget, jittered exponential backoff, and clear timeout limits. Retry only idempotent operations or writes protected by idempotency keys. The circuit should open after a failure threshold, fail fast temporarily, and use limited half-open probes before recovery.

**Why it helps here:** It would reduce retry amplification, give the dependency room to recover, and replace repeated five-second waits with controlled failure behaviour.

**Complexity:** Medium  
**Business impact:** Smaller blast radius, faster customer responses during degradation, and lower duplicate-order risk.

### 3. Distributed Tracing

**Problem:** The logs show that requests take about five seconds but not whether the time is spent in the API, `internal-service`, connection acquisition, or query execution.

**Solution:** Add OpenTelemetry tracing across API → `internal-service` → database, including separate spans for connection acquisition and query execution. Include trace IDs in logs and retain all error and slow-request traces.

**Why it helps here:** A trace could immediately distinguish a 4.2-second connection wait from a 4.8-second query, reducing uncertainty between the leading hypotheses.

**Complexity:** Medium–High  
**Business impact:** Faster root-cause identification, lower mean time to resolution, and better evidence during escalation.

## 10. Limitations

- Only the supplied scenario and log sample are available.
- The logs do not identify which connection pool was saturated.
- The ordering of CPU saturation, pool saturation, and errors is unknown.
- The slow query may be a cause or a consequence of contention.
- No data loss is shown, but order write integrity would require separate verification.

## 11. Conclusion

The available evidence supports prioritising the `internal-service` and database path. The leading hypothesis is that slow downstream work held connections long enough to saturate the pool, causing request deadlines and 502 responses, with retries and CPU load as possible amplifiers or consequences.

This is not a confirmed root cause. A strong support response would first confirm scope, test the hypotheses with connection and database telemetry, apply only evidence-based mitigations, communicate customer impact early, and escalate with a concise package when the incident does not recover.
