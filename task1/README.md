# Task 1 — Data Consistency & Real-Time Behavior

This directory contains the scripts, supporting analysis, and test data used for Task 1.

## Final Report

See [`../report/task1.md`](../report/task1.md) for the consolidated assessment report.

## Contents

| File                                                                   | Purpose                                        |
| ---------------------------------------------------------------------- | ---------------------------------------------- |
| [`analyzer.py`](./analyzer.py)                                         | Candle-data consistency and integrity analysis |
| [`load_test.py`](./load_test.py)                                       | Concurrent REST API load testing               |
| [`data_intergity.md`](./data_intergity.md)                             | Detailed data-integrity investigation          |
| [`realtime_behavior_under_load.md`](./realtime_behavior_under_load.md) | Load-test and real-time behavior analysis      |
| [`operational_risk_review.md`](./operational_risk_review.md)           | Operational risk analysis                      |
| [`incident_simulation.md`](./incident_simulation.md)                   | Simulated support incident investigation       |
| [`improvements.md`](./improvements.md)                                 | Proposed monitoring and product improvements   |
| [`data/`](./data/)                                                     | Persisted candle and load-test results         |

## Running the Analysis

From the repository root, with dependencies installed:

```bash
python3 task1/analyzer.py
python3 task1/load_test.py
```

Generated outputs are written to `task1/data/`.
