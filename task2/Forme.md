# Task 2 — Incident Analysis

## Scenario Summary

At 14:02, monitoring alerts fire:
- API error rate jumps from 0.2% → 7%
- CPU at 95% on 2 of 5 instances
- No deployments in last 24 hours
- One enterprise customer reporting intermittent 502 errors
- Traffic volume normal

---

## 1. Investigation Plan

### Initial Observation

Working backwards from the logs:

14:01:58 GET /api/orders 200 120ms ← system healthy
14:02:01 GET /api/orders 502 5320ms ← failure begins
14:02:10 connection pool: 100/100 active, 0 idle ← pool exhausted
14:02:11 slow query detected: 4800ms ← DB bottleneck
14:02:15 GET /api/health 200 8ms ← health endpoint responsive


The health check returning 200 in 8ms shows the API health endpoint
is responsive, but does not rule out downstream dependency problems.

### What I Check First

**Step 1 — Determine scope:**

Is it one customer or all customers?
Is it only /api/orders or other endpoints too?
Is it 2 instances or all 5?

This separates "isolated problem" from "system-wide failure" and
determines urgency.

**Step 2 — What changed at 14:02:**

No deployments in the previous 24 hours makes a recent deployment
less likely as the trigger, but does not completely rule out
application or configuration issues.
Traffic normal → makes a traffic spike unlikely
→ something changed internally at that moment


**Step 3 — Investigate DB hypothesis:**

Connection pool 100 active / 0 idle → pool fully exhausted
Slow query 4800ms → DB queries taking significantly longer than normal
Context deadline exceeded → upstream operation exceeded its deadline
(could be waiting for DB connection, slow query execution, or other downstream issue)


The chain to verify:

DB query slows → connections held longer → pool fills up →
new requests wait → timeout → 502 → internal-service retries →
more load → CPU rises on 2 instances


Each step is a hypothesis to confirm, not a confirmed fact.
I would verify connection acquisition wait time and confirm
whether the slow query is directly responsible.

**Step 4 — Check retries:**

The logs show:

WARN retrying request to internal-service


Application-level retry behavior that may be generating additional
load on an already struggling system. Retries may consume additional
connections and CPU, increasing load on the affected components.
This should be verified with retry metrics and process-level CPU data.

### Hypotheses

**H1 — DB contention (leading hypothesis):**
Slow DB query may be causing connection pool exhaustion leading to
cascade of timeouts. Requires verification.
Evidence pointing here: 100/100 pool + 4800ms query + upstream timeouts.

**H2 — CPU saturation:**
2/5 instances at 95% CPU. Could be cause or consequence.
Need to check: did CPU spike before or after errors started?
Are high-CPU instances the same ones generating 502s?

**H3 — Retry amplification:**
Retries may be turning a partial failure into a full incident.
Retries may consume additional connections and CPU, increasing
load on the affected components.

### Scope and Impact

**Scope:**
- 2 of 5 instances affected by CPU saturation
- /api/orders shows intermittent 502s; health check remains healthy
- One enterprise customer confirmed affected
- Need to verify: are other customers affected? Other endpoints?

**Impact:**
- Error rate 7% (baseline 0.2%) — significant increase from normal
- Request latency 5000ms+ vs normal 120ms
- Enterprise customer is experiencing intermittent 502 errors on the affected API endpoint
- No evidence of data loss in the provided logs; data integrity would need to be verified separately

---

## 2. Escalation Decision

**Decision: Yes, escalate.**

### Timing Reasoning

At 30 minutes — I would escalate because the error rate remains
at 5–8%, customer impact continues, and the issue has not been
resolved or shown improvement.

I would escalate earlier if:
- Error rate were increasing rather than stable
- More customers became affected
- A critical function became completely unavailable
- The issue showed signs of spreading to other services

I would continue initial investigation in parallel with escalation
rather than waiting for full diagnosis before notifying senior resources.

### Short-term Mitigation to Try Before/During Escalation

If 3 instances are healthy and only 2 are CPU-saturated, consider
temporarily routing traffic away from the 2 degraded instances.
Risk: if DB is the bottleneck, more instances = more DB connections,
potentially worsening pool exhaustion. Proceed with caution.

### Who to Escalate To

- Senior backend/application engineer
- DBA team (to investigate slow query, check DB locks and indexes)
- Incident commander if enterprise SLA breach is approaching

### Escalation Message

INCIDENT — 14:02 to present (30+ minutes)

Impact:

API error rate: 0.2% → 5-8% (ongoing)
Enterprise customer experiencing intermittent 502 errors
/api/orders endpoint affected

Infrastructure:

2/5 instances at ~95% CPU
Traffic volume: normal
Deployments: none in last 24 hours

Evidence from logs:

DB connection pool: 100 active / 0 idle (fully exhausted)
Slow query detected: 4800ms
Multiple "context deadline exceeded" errors
Retries to internal-service observed

Leading hypothesis:
Slow DB query may be holding connections longer than normal,
potentially exhausting the connection pool. New requests cannot
acquire connections, timeout, and retry — possibly amplifying
load on an already degraded system. Requires verification.

Actions taken:

Analyzed logs and metrics
Identified DB connection pool exhaustion and slow queries as
key evidence; DB contention is the leading root-cause hypothesis
Confirmed upstream timeout pattern
Confirmed no deployment or traffic spike

Actions needed:

Investigate slow DB query (query plan, locks, indexes)
Confirm whether CPU saturation is cause or consequence
Assess whether retry behavior is amplifying the incident
Evaluate connection pool size vs current load requirements

---

## 3. Preventive Improvements

### Improvement 1 — DB Connection Pool Monitoring

**Problem:**
The connection pool reached 100/100 with no alert. By the time
customers were seeing errors, the pool was already fully exhausted.

**Solution:**
Add alerts at multiple thresholds:
- Warning at 70% pool utilization (70/100 connections)
- Critical at 85% pool utilization (85/100 connections)
- Alert on query latency > 1000ms
- Alert on connection wait time > 500ms

**Why it helps:**
Catches pool exhaustion before it becomes complete failure.
At 70% utilization you have time to investigate and mitigate
before customers are impacted.

**Effect:** Improves detection, reduces customer impact window.

---

### Improvement 2 — Circuit Breaker + Retry Controls

**Problem:**

WARN retrying request to internal-service

Failed requests are being retried, potentially generating additional
load on an already struggling system.

**Solution:**
Implement circuit breaker pattern with exponential backoff:

Without circuit breaker (current):
Request fails → retry immediately → fails → retry → fails → retry
→ additional load on the struggling DB

With circuit breaker:
Request fails → retry after 1s → fails → retry after 2s → fails
→ circuit OPENS: stop sending requests temporarily
→ after cooldown: circuit enters HALF-OPEN
→ allow limited test requests
→ if healthy: circuit returns to CLOSED (normal operation)
→ if still failing: circuit returns to OPEN


**Why it helps:**
Prevents retry storms from amplifying downstream failures.
Gives degraded services time to recover rather than being
continuously hammered.

**Effect:** Reduces blast radius of incidents, prevents cascading failures.

---

### Improvement 3 — Distributed Tracing

**Problem:**
During this incident, diagnosing required manually correlating
separate log lines across layers:

API logs → internal service logs → DB logs

It was unclear where in the chain the 5 seconds were being spent.

**Solution:**
Implement distributed tracing (Jaeger, Zipkin, or Datadog APM).
Each request gets a unique trace ID that flows through all layers.

Example of what a trace might show:

Request trace abc123:
→ API layer: 5ms
→ internal service: 45ms
→ waiting for DB conn: 4200ms
→ DB query execution: 600ms
→ Total: 4850ms


Tracing could show whether the majority of the 5-second latency
was spent waiting for a DB connection, executing the query, or
processing within the internal service — information that was
not immediately available from the logs alone.

**Why it helps:**
Dramatically faster root cause identification in future incidents.
Instead of manually correlating logs across layers, the trace
shows exactly where time is being spent.

**Effect:** Faster investigation, more precise root cause identification.

---

## Summary

| | Finding |
|---|---|
| Root cause hypothesis | Slow DB query may be causing connection pool exhaustion leading to cascade of timeouts — requires verification |
| Escalation | Yes, at 30 minutes — customer impacted, not self-resolving, no improvement trend |
| Key improvement 1 | Alert on DB pool utilization before exhaustion |
| Key improvement 2 | Circuit breaker + exponential backoff on retries |
| Key improvement 3 | Distributed tracing across all service layers |