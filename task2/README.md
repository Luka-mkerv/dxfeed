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
14:02:15 GET /api/health 200 8ms ← API process alive


The health check returning 200 in 8ms shows the API health endpoint is responsive, 
but does not rule out downstream dependency problems.

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
application/configuration issues.
Traffic normal → eliminates traffic spike
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
load on an already struggling system. Retry activity may be 
contributing to CPU utilization on the 2 affected instances — 
this should be verified with retry metrics and process-level CPU data.

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
Retries turning a partial failure into a full incident.
Each retry consumes more connections and CPU.

### Scope and Impact

**Scope:**
- 2 of 5 instances affected by CPU saturation
- /api/orders endpoint failing (health check fine)
- One enterprise customer confirmed affected
- Need to verify: are other customers affected? Other endpoints?

**Impact:**
- Error rate 7% (baseline 0.2%) — significant increase from normal
- Request latency 5000ms+ vs normal 120ms
- Enterprise customer is experiencing intermittent 502 errors on the affected API endpoint
- No data loss confirmed — failures are timeouts not corruption

---

## 2. Escalation Decision

**Decision: Yes, escalate.**

### Timing Reasoning

**Not earlier** — needed time to properly diagnose. A DB connection 
pool issue can sometimes self-resolve if the slow query finishes 
and connections free up. Escalating immediately without evidence 
wastes senior engineer time.

**At 30 minutes** — error rate still 5-8% with no improvement trend.
Enterprise customer still impacted. Root cause not confirmed or fixed.
Risk of further degradation outweighs waiting longer.

**Not later** — an enterprise customer experiencing 502 errors for 
30+ minutes with no resolution in sight requires escalation. 
The problem is not self-resolving.

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
Slow DB query holding connections for ~5 seconds, exhausting the
100-connection pool. New requests cannot acquire connections,
timeout, and retry — amplifying load on an already degraded system.

Actions taken:

Analyzed logs and metrics
Confirmed DB connection pool exhaustion
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
- Alert on query latency > 1000ms (slow query detection)
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

Failed requests are being retried immediately, generating more load 
on an already struggling DB. This turns a partial problem into 
a full incident.

**Solution:**
Implement circuit breaker pattern with exponential backoff:

Without circuit breaker (current):
Request fails → retry immediately → fails → retry → fails → retry
→ 3x load on struggling DB

With circuit breaker:
Request fails → retry after 1s → fails → retry after 2s → fails
→ circuit OPENS: stop sending requests for 30 seconds
→ DB gets breathing room to recover
→ circuit CLOSES slowly: test with small traffic
→ if recovering → resume normal operation


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
Each request gets a unique trace ID that flows through all layers:

Request trace abc123:
→ API layer: 5ms
→ internal service: 45ms
→ waiting for DB conn: 4200ms ← immediately visible
→ DB query execution: 600ms
→ Total: 4850ms


**Why it helps:**
In this incident, tracing would have shown immediately that 
4.2 seconds were spent waiting for a DB connection — not in 
the API or internal service. Investigation time: seconds instead 
of minutes.

**Effect:** Dramatically faster root cause identification in future incidents.

---

## Summary

| | Finding |
|---|---|
| Root cause hypothesis | DB query slowdown → connection pool exhaustion → cascade of timeouts |
| Escalation | Yes, at 30 minutes — customer impacted, not self-resolving |
| Key improvement 1 | Alert on DB pool utilization before exhaustion |
| Key improvement 2 | Circuit breaker + exponential backoff on retries |
| Key improvement 3 | Distributed tracing across all service layers |