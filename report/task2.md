# Task 2 — API Incident Investigation

## 1. Objective

Perform a **scenario-based** incident investigation for an API reliability event. The goal is to scope impact, evaluate evidence, form testable hypotheses, define escalation criteria, and propose preventive improvements.

This is **not** a real production incident. No live systems were remediated as part of this task; actions below describe what an investigator **would** do.

## 2. Incident Summary

At **14:02**:

| Signal | Observation |
| ------ | ----------- |
| API error rate | 0.2% → 7% |
| CPU | ~95% on 2 of 5 instances |
| Deployments | None in the previous 24 hours |
| Traffic | Normal |
| Customer report | One enterprise customer reporting intermittent 502s |

## 3. Initial Scope and Impact

**Known:**

- Error rate elevated service-wide (as reported by monitoring)
- Two of five instances show high CPU
- At least one enterprise customer is impacted on `/api/orders`
- `/api/health` remains healthy (200 in ~8 ms)

**Unknown / to confirm first:**

- Whether the 7% error rate is global or concentrated by endpoint, instance, customer, or region
- Whether other customers or endpoints are affected
- Whether the high-CPU instances are the same instances producing 502s

**Impact framing:** Business traffic can be unhealthy even when `/api/health` is healthy. Health checks do not prove dependency or business-path health.

## 4. Investigation and Evidence

Representative logs around the onset:

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

**Evidence (observed in the scenario materials):**

| Evidence | What it indicates |
| -------- | ----------------- |
| ~5 s 502s labeled “upstream timeout” | Requests are failing after waiting on an upstream dependency |
| `context deadline exceeded` | Upstream work exceeded its deadline |
| Retry warnings to `internal-service` | Retries are occurring during degradation |
| Connection pool 100 active / 0 idle | Pool saturation at the time of the logs |
| Slow query ~4.8 s | Database work is abnormally slow in at least one case |
| Healthy `/api/health` | Local health endpoint is not a proxy for `/api/orders` health |

## 5. Hypotheses

| Hypothesis | Support | Status |
| ---------- | ------- | ------ |
| DB contention / slow query contributing to pool exhaustion and timeouts | Slow query + exhausted pool + upstream deadlines | Leading hypothesis; **not proven** |
| CPU saturation on 2/5 instances | ~95% CPU on affected instances | Possible contributor or consequence; sequence unknown |
| Retry amplification | Retry logs during upstream failures | Plausible amplifier; needs retry metrics |

**Important distinction:** The database is **not** proven to be the root cause. The strongest available evidence supports prioritizing dependency/database investigation; confirmation requires additional metrics (connection wait time, query plans/locks, per-instance correlation, retry volume).

## 6. Likely Failure Path

A coherent **working model** (hypothesis, not confirmed root cause):

1. Downstream work (e.g., DB query) slows
2. Connections are held longer and the pool fills (100 active / 0 idle)
3. New requests wait, then exceed deadlines → upstream timeouts / 502s
4. Retries add load while the dependency is already degraded
5. CPU rises on some instances as a contributor and/or consequence

Each step needs validation before being treated as confirmed cause.

## 7. Immediate Investigation / Mitigation Actions

These are the actions an investigator **would** take; they were not executed against a live environment for this assessment.

**Investigate:**

1. Confirm scope: endpoints, instances, customers, regions
2. Correlate error rate, latency, CPU, pool utilization, DB latency, and traffic over the same window
3. Trace `/api/orders` → `internal-service` → database
4. Inspect slow-query details, locks, and connection wait times
5. Quantify retry rate and whether retries correlate with pool pressure

**Possible short-term mitigations (with caution):**

- Temporarily reduce traffic to saturated instances **if** the problem is instance-local
- Avoid blindly scaling out if DB pool exhaustion is shared — more instances can worsen pool pressure
- Reduce aggressive retries once retry amplification is confirmed

## 8. Escalation Criteria

**Escalate after ~30 minutes if:**

- Error rate remains around 5–8%
- CPU remains high on affected instances
- Root cause remains unresolved

**Escalate earlier if:**

- Error rate increases
- Customer impact broadens
- More instances are affected
- Wider availability / SLA risk appears

**Escalation targets:** senior backend/application engineer; DBA; incident commander if enterprise SLA criteria apply.

**Escalation package should include:**

- Error rate and duration
- Affected instances / endpoints / customers
- CPU and latency
- Relevant logs
- DB connection-pool state
- Slow-query evidence
- Actions taken and results
- Current hypotheses and known unknowns

## 9. Preventive Improvements

1. **DB connection-pool monitoring** — alert before exhaustion (utilization, wait time, query latency)
2. **Circuit breaker + exponential backoff** — limit retry amplification against an unhealthy dependency
3. **Distributed tracing** — locate where the multi-second latency is spent across API → internal service → DB

## 10. Limitations

- Scenario-based materials only; no live production telemetry beyond the provided summary
- Causal chain not confirmed with database-level investigation
- CPU vs dependency ordering (cause vs effect) is unresolved from the given logs alone
- No evidence of data loss was provided; integrity would need separate verification

## 11. Conclusion

The strongest evidence points to a **dependency/resource bottleneck** involving `internal-service` / database behavior, with retries and CPU saturation as potential amplifiers or consequences. Database contention is a leading hypothesis supported by timeouts, pool exhaustion, and a slow query — but it is **not** a proven root cause from the supplied evidence alone.

Support-quality investigation means separating evidence from hypothesis, confirming scope before broad claims, and escalating with a clear package when impact persists.
