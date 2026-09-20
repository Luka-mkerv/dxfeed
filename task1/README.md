# Task 1 — Data Consistency & Real-Time Behavior

Scripts, supporting analysis, and test data for Task 1.

## Final report

See [`../report/task1.md`](../report/task1.md) for the consolidated assessment report.

## Scope caveats

* Part 1 used **historical REST candle data** from the dxFeed demo endpoint.
* **No real-time / streaming validation** was performed.
* **No Radar / live-feed comparison** was performed.
* The EUR/USD “frozen candle” scenario in [`incident_simulation.md`](./incident_simulation.md) is a **simulation**, not a confirmed production incident.

## Contents

| File | Purpose |
| ---- | ------- |
| [`analyzer.py`](./analyzer.py) | Candle-data consistency and integrity analysis |
| [`load_test.py`](./load_test.py) | Concurrent REST API load testing |
| [`data_integrity.md`](./data_integrity.md) | Detailed data-integrity investigation |
| [`realtime_behavior_under_load.md`](./realtime_behavior_under_load.md) | Load-test and concurrency behavior analysis |
| [`operational_risk_review.md`](./operational_risk_review.md) | Operational risk analysis |
| [`incident_simulation.md`](./incident_simulation.md) | Simulated support incident investigation |
| [`improvements.md`](./improvements.md) | Proposed monitoring and product improvements |
| [`data/`](./data/) | Persisted candle CSVs and load-test results |

## Running the analysis

From the repository root, with a Python environment that provides `requests` and `pandas`:

```bash
python3 task1/analyzer.py
python3 task1/load_test.py
```

Generated outputs are written to `task1/data/`.

This repository does not include a `requirements.txt`. Install the packages above in your active environment (for example the existing project `venv/`) before running the scripts.
