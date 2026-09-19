# Task 2 — Incident Investigation

## Objective

Investigate an API reliability incident, determine the likely failure path, assess customer impact, define escalation criteria, and propose preventive improvements.

## Incident Summary

At 14:02, API error rate increased from **0.2% to 7%**. CPU utilization reached approximately **95% on 2 of 5 instances**. Traffic was normal and there had been no deployments during the previous 24 hours. One enterprise customer reported intermittent **502 responses**.

Relevant logs showed:

* `502` responses taking approximately 5 seconds and ending with upstream timeouts.
* Requests to the internal service failing with `context deadline exceeded`.
* Retries occurring after upstream failures.
* Database connection pool fully utilized: **100 active, 0 idle**.
* A slow database query taking approximately **4.8 seconds**.
* `/api/health` remained healthy.

## Investigation Approach

I would investigate from the external symptom toward the dependency causing it:

1. **Confirm scope and impact**

   * Verify whether the 7% error rate is global or concentrated by endpoint, instance, customer, or region.
   * Check whether the enterprise customer's 502s correlate with specific instances or requests.

2. **Correlate application and infrastructure metrics**

   * Compare error rate, latency, CPU, connection-pool utilization, database latency, and request volume over the same time period.
   * Check whether the affected instances show materially different behavior from the remaining instances.

3. **Investigate the upstream timeout**

   * Trace the request path from API → internal service → database.
   * Examine the `context deadline exceeded` errors and retry activity.
   * Check database connection availability and slow-query behavior.

4. **Test competing hypotheses**

   * **Database contention / slow queries:** supported by the 4.8s query and exhausted connection pool, but not proven from the supplied evidence alone.
   * **CPU saturation:** high CPU on 2 instances may contribute to increased request latency.
   * **Retry amplification:** retries may increase load when the upstream dependency is already degraded.

The immediate evidence therefore points toward a dependency/resource bottleneck causing requests to exceed their deadlines, with database contention being a leading hypothesis requiring further validation.

## Scope and Impact

The incident affects API reliability, with the observed error rate rising to 7% and at least one enterprise customer experiencing intermittent 502 responses. The healthy `/api/health` endpoint does not establish that business API traffic is healthy; dependency-specific failures can still occur.

I would prioritize determining whether the failures are isolated to the two high-CPU instances or affect the wider service and whether database saturation is shared across instances.

## Escalation

If, after **30 minutes**, the error rate remains around **5–8%**, CPU remains high on 2 instances, and the root cause is unresolved, I would escalate.

The escalation should include:

* Current error rate and duration.
* Affected instances/endpoints/customers.
* CPU and latency metrics.
* Relevant 502/upstream-timeout logs.
* Database connection-pool state.
* Slow-query evidence.
* Actions already taken and their results.
* Current hypotheses and remaining unknowns.

The primary escalation targets would be a **senior backend/application engineer** and **DBA**. An **incident commander** should also be involved if the enterprise customer impact meets the organization's incident/SLA criteria.

I would escalate earlier if the error rate or customer impact increases materially, additional instances become affected, or the service approaches a broader availability risk.

## Preventive Improvements

### 1. Database Connection-Pool Monitoring

Monitor pool utilization, connection wait time, and database query latency with alerts before the pool is exhausted.

**Purpose:** Detection and prevention.

### 2. Circuit Breaker and Exponential Backoff

Limit retries against an unhealthy upstream dependency and use exponential backoff to reduce retry amplification.

**Purpose:** Impact reduction and prevention.

### 3. Distributed Tracing

Introduce request tracing across the API, internal service, and database dependency.

**Purpose:** Faster detection and diagnosis by identifying where request latency is introduced.

## Key Takeaway

The incident should be investigated as a dependency and resource-exhaustion problem rather than assuming that high CPU is the root cause. The strongest available evidence is the combination of upstream timeouts, retry activity, an exhausted connection pool, and a 4.8-second database query; however, additional metrics and database-level investigation are required to confirm the causal chain.
