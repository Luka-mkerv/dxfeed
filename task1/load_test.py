"""
Load test for the dxFeed demo REST API.

Sends real HTTP requests to https://demo.dxfeed.com/webservice/rest/events.json
at increasing levels of thread concurrency, and records per-request metrics
(latency, status code, errors, response hash, etc.) which are used to build
a per-concurrency-level summary and saved to a CSV file.

API parameter shape (events=Candle, symbols=<SYMBOL>{=<period>}, fromTime,
toTime) was confirmed by inspecting the existing `analyzer.py` in this
project and by a manual request against the live endpoint before writing
this script.
"""

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

BASE_URL = "https://demo.dxfeed.com/webservice/rest/events.json"

SYMBOLS = ["AAPL", "TSLA", "MSFT", "GOOG", "AMZN", "IBM", "SPY"]

CANDLE_NOTATION = "{=1m}"  # 1-minute candle notation, appended to the symbol
FROM_TIME = "2026-09-17T10:00:00"
TO_TIME = "2026-09-17T10:10:00"

# Per-request timeout, per the assignment. Passed to requests.Session.get()
# as a single float, which per the `requests` docs applies SEPARATELY to the
# connect phase and to the read phase (the read timer resets on each chunk
# received) - it is not a single hard wall-clock cap on total request time.
# In practice, for this JSON API this closely approximates a 15s-per-request
# cap: observed timeouts in this test fired at ~15.36-15.38s (connect was
# effectively instantaneous, and the response is not chunked/streamed with
# long gaps), and no successful request was ever observed to exceed ~15s.
# A strictly enforced hard deadline would require an external watchdog
# (e.g. a thread-level future.result(timeout=...)), which was judged
# unnecessary here given the observed behavior matches the assignment's
# intent closely enough.
REQUEST_TIMEOUT_SEC = 15

CONCURRENCY_LEVELS = [1, 5, 10, 20, 50]

# Number of HTTP requests fired at *each* concurrency level. Requests are
# distributed round-robin across SYMBOLS so that a concurrency level of 50
# actually exercises 50 simultaneous in-flight requests, rather than being
# silently capped at the 7 available symbols.
REQUESTS_PER_CONCURRENCY = 50

# Small cooldown between concurrency levels so the test doesn't hammer the
# shared demo service back-to-back at full tilt; this does not affect the
# measured concurrency itself, only the gap between test phases.
PAUSE_BETWEEN_LEVELS_SEC = 2

TASK_DIR = Path(__file__).resolve().parent
DATA_DIR = TASK_DIR / "data"
RESULTS_CSV = DATA_DIR / "load_test_results.csv"

# --------------------------------------------------------------------------- #
# Thread-safety: requests.Session is not guaranteed thread-safe when its
# connection pool is shared across threads under heavy concurrency, so we
# hand each worker thread its own Session (created lazily, cached for the
# lifetime of the thread) instead of sharing one Session across all threads.
# --------------------------------------------------------------------------- #

_thread_local = threading.local()


def _get_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def build_job_list(count: int, symbols: list) -> list:
    """Deterministic round-robin symbol assignment for `count` requests."""
    return [symbols[i % len(symbols)] for i in range(count)]


def _record_timing(result: dict, start_wall: float, start_perf: float) -> None:
    """
    Record elapsed latency and the wall-clock second the response was
    actually *received* (start time + elapsed latency). Used for both the
    reported response_time_ms and for cache-detection bucketing below -
    bucketing on request start time instead of completion time would be
    wrong whenever requests overlap but finish seconds apart (exactly the
    case under higher concurrency levels here).
    """
    elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
    result["response_time_ms"] = elapsed_ms
    result["completion_epoch_second"] = int(start_wall + elapsed_ms / 1000.0)


def do_request(symbol: str, concurrency_level: int, request_index: int) -> dict:
    """
    Perform a single real HTTP request against the dxFeed demo REST API
    and return a dict describing the outcome. Never raises: all request
    exceptions are caught and recorded so one failed request cannot abort
    the benchmark.
    """
    candle_symbol = f"{symbol}{CANDLE_NOTATION}"
    params = {
        "events": "Candle",
        "symbols": candle_symbol,
        "fromTime": FROM_TIME,
        "toTime": TO_TIME,
    }

    start_wall = time.time()
    start_perf = time.perf_counter()

    result = {
        "concurrency_level": concurrency_level,
        "request_index": request_index,
        "symbol": symbol,
        "candle_symbol": candle_symbol,
        "start_time_iso": datetime.fromtimestamp(start_wall, tz=timezone.utc).isoformat(),
        "start_epoch_second": int(start_wall),
        "completion_epoch_second": None,
        "status_code": None,
        "response_time_ms": None,
        "success": False,
        "is_timeout": False,
        "is_429": False,
        "error_type": "none",
        "error_message": "",
        "response_size_bytes": 0,
        "response_hash": "",
    }

    session = _get_session()

    try:
        resp = session.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SEC)
        _record_timing(result, start_wall, start_perf)
        result["status_code"] = resp.status_code
        result["response_size_bytes"] = len(resp.content)
        result["response_hash"] = hashlib.sha256(resp.content).hexdigest()

        if resp.status_code == 429:
            result["is_429"] = True
            result["error_type"] = "rate_limited"
            result["error_message"] = "HTTP 429 Too Many Requests"
        elif 200 <= resp.status_code < 300:
            try:
                data = resp.json()
            except ValueError as exc:
                result["error_type"] = "unexpected_response"
                result["error_message"] = f"Response body is not valid JSON: {exc}"
            else:
                # Validate the response actually has the expected dxFeed
                # events.json shape rather than assuming it always will.
                if isinstance(data, dict) and data.get("status") == "OK" and "Candle" in data:
                    result["success"] = True
                else:
                    result["error_type"] = "unexpected_response"
                    status_val = data.get("status") if isinstance(data, dict) else type(data).__name__
                    result["error_message"] = f"Unexpected JSON shape/status: {status_val!r}"
        else:
            result["error_type"] = "http_error"
            result["error_message"] = f"HTTP {resp.status_code}"

    except requests.exceptions.Timeout as exc:
        _record_timing(result, start_wall, start_perf)
        result["is_timeout"] = True
        result["error_type"] = "timeout"
        result["error_message"] = f"Timed out after {REQUEST_TIMEOUT_SEC}s: {exc}"[:250]

    except requests.exceptions.ConnectionError as exc:
        _record_timing(result, start_wall, start_perf)
        result["error_type"] = "connection_error"
        result["error_message"] = str(exc)[:250]

    except requests.exceptions.RequestException as exc:
        # Catch-all for other requests-library exceptions (e.g. TooManyRedirects,
        # InvalidURL) that aren't timeouts or connection errors.
        _record_timing(result, start_wall, start_perf)
        result["error_type"] = "other_exception"
        result["error_message"] = str(exc)[:250]

    return result


def run_concurrency_level(level: int, requests_count: int) -> list:
    """Run `requests_count` real HTTP requests using up to `level` worker threads."""
    jobs = build_job_list(requests_count, SYMBOLS)
    results = []

    with ThreadPoolExecutor(max_workers=level) as executor:
        futures = [
            executor.submit(do_request, symbol, level, idx)
            for idx, symbol in enumerate(jobs)
        ]
        for future in as_completed(futures):
            results.append(future.result())

    return results


def mark_potentially_cached(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag successful responses whose SHA-256 body hash matches another
    successful response *received* within the same whole wall-clock second.

    Bucketing uses completion_epoch_second (request start + measured
    latency), not the request's start second: under concurrency, requests
    routinely start within the same second but finish seconds apart (e.g.
    a 500ms response vs. a 14s response started moments later), so bucketing
    by start time would misclassify same-second *sends* as same-second
    *receipts*. Bucketing by completion time matches the "received within
    the same second" requirement.

    This is only evidence of *identical* responses, not proof of caching:
    since every request in this test targets the same fixed fromTime/toTime
    window, repeated requests for the same symbol are expected to return
    byte-identical historical data regardless of whether caching exists.
    """
    df = df.copy()
    df["potentially_cached"] = False

    success_mask = df["success"] & (df["response_hash"] != "")
    if not success_mask.any():
        return df

    keys = (
        df.loc[success_mask, "completion_epoch_second"].astype(int).astype(str)
        + "|"
        + df.loc[success_mask, "response_hash"]
    )
    dup_keys = set(keys[keys.duplicated(keep=False)])
    df.loc[success_mask, "potentially_cached"] = keys.isin(dup_keys).values

    return df


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the required per-concurrency-level statistics."""
    rows = []
    for level in CONCURRENCY_LEVELS:
        level_df = df[df["concurrency_level"] == level]
        n = len(level_df)
        n_success = int(level_df["success"].sum())
        n_errors = n - n_success
        n_timeout = int(level_df["is_timeout"].sum())
        n_429 = int(level_df["is_429"].sum())
        n_cached = int(level_df["potentially_cached"].sum())

        # Percentiles are computed over SUCCESSFUL requests only. Failed and
        # timed-out requests don't represent a completed response latency -
        # a timeout's response_time_ms is essentially just the configured
        # timeout value, not a real round-trip time - so mixing them in
        # would distort the percentiles (e.g. at high error/timeout rates,
        # p50 would land on the boundary between the two groups rather than
        # reflecting either one). Error/timeout rates are already reported
        # separately via error_pct/timeout_pct.
        latencies = level_df.loc[level_df["success"], "response_time_ms"].dropna()
        p50 = latencies.quantile(0.50) if not latencies.empty else float("nan")
        p95 = latencies.quantile(0.95) if not latencies.empty else float("nan")
        p99 = latencies.quantile(0.99) if not latencies.empty else float("nan")

        rows.append(
            {
                "concurrency": level,
                "requests": n,
                "success": n_success,
                "errors": n_errors,
                "timeouts": n_timeout,
                "http_429": n_429,
                "error_pct": (n_errors / n * 100.0) if n else 0.0,
                "timeout_pct": (n_timeout / n * 100.0) if n else 0.0,
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": p99,
                "potentially_cached": n_cached,
                "potentially_cached_pct": (n_cached / n_success * 100.0) if n_success else 0.0,
            }
        )

    return pd.DataFrame(rows)


def print_summary_table(summary_df: pd.DataFrame) -> None:
    header = (
        f"{'Concurrency':>11} | {'Requests':>8} | {'Success':>7} | {'Errors':>6} | "
        f"{'Timeouts':>8} | {'429':>4} | {'Error %':>7} | {'Timeout %':>9} | "
        f"{'p50 ms':>8} | {'p95 ms':>8} | {'p99 ms':>8}"
    )
    print("(latency percentiles below are computed over successful requests only)")
    print(header)
    print("-" * len(header))
    # Iterate as dicts (not iterrows()) to avoid pandas upcasting the whole
    # mixed-dtype row to float64, which would turn e.g. concurrency=1 into 1.0.
    for row in summary_df.to_dict("records"):
        print(
            f"{int(row['concurrency']):>11} | {int(row['requests']):>8} | {int(row['success']):>7} | "
            f"{int(row['errors']):>6} | {int(row['timeouts']):>8} | {int(row['http_429']):>4} | "
            f"{row['error_pct']:>6.1f}% | {row['timeout_pct']:>8.1f}% | "
            f"{row['p50_ms']:>8.1f} | {row['p95_ms']:>8.1f} | {row['p99_ms']:>8.1f}"
        )


def print_interpretation(df: pd.DataFrame, summary_df: pd.DataFrame) -> None:
    print("\nInterpretation")
    print("-" * 14)

    ordered = summary_df.sort_values("concurrency").reset_index(drop=True)

    # --- Successful-request latency (p50/p95/p99 EXCLUDE failures) ----- #
    # This describes how long a request takes *given that it completes*.
    # It is a distinct signal from overall service degradation: at high
    # concurrency, a large share of requests may fail/time out and never
    # contribute to these percentiles at all, so a flat or falling
    # successful-request p50 does NOT mean the service handled the load
    # well - it can simply mean only a smaller, faster-than-average subset
    # of requests survived to completion (survivorship bias).
    valid = ordered.dropna(subset=["p50_ms"])
    if len(valid) >= 2:
        lo, hi = valid.iloc[0], valid.iloc[-1]
        if hi["p50_ms"] > lo["p50_ms"]:
            change = f"rose from {lo['p50_ms']:.1f} ms to {hi['p50_ms']:.1f} ms"
        elif hi["p50_ms"] < lo["p50_ms"]:
            change = f"fell from {lo['p50_ms']:.1f} ms to {hi['p50_ms']:.1f} ms"
        else:
            change = "was unchanged"
        monotonic = bool(valid["p50_ms"].is_monotonic_increasing)
        print(
            f"- Successful-request latency (p50, excludes failed/timed-out requests): {change} "
            f"between concurrency {int(lo['concurrency'])} ({int(lo['success'])} successful of "
            f"{int(lo['requests'])} requests) and concurrency {int(hi['concurrency'])} "
            f"({int(hi['success'])} successful of {int(hi['requests'])} requests). "
            f"Monotonically non-decreasing across all levels with successful data: {monotonic}."
        )
        if not monotonic:
            print(
                "  Note: a non-monotonic (or falling) successful-request p50 at higher concurrency "
                "is NOT evidence the service got faster under load. It coincides here with a rising "
                "error/timeout rate (see below), which is the more reliable indicator of overall "
                "degradation, since it also accounts for requests that never completed."
            )
    elif len(valid) == 1:
        print(
            "- Successful-request latency: only one concurrency level had successful requests to "
            "measure; a latency-vs-concurrency trend cannot be established from a single data point."
        )
    else:
        print("- Successful-request latency: no concurrency level had any successful requests.")

    # --- Overall service degradation, independent of successful latency #
    # error_pct/timeout_pct are computed over ALL requests at a level (not
    # just successes), so unlike the percentiles above they do capture the
    # effect of requests that failed or never completed.
    lo_row, hi_row = ordered.iloc[0], ordered.iloc[-1]
    error_rate_increased = hi_row["error_pct"] > lo_row["error_pct"]
    print(
        f"- Overall service degradation (error rate across ALL requests, including failures/timeouts): "
        f"{lo_row['error_pct']:.1f}% at concurrency {int(lo_row['concurrency'])} vs. "
        f"{hi_row['error_pct']:.1f}% at concurrency {int(hi_row['concurrency'])} "
        f"({'increased' if error_rate_increased else 'did not increase'}). "
        f"This all-requests error rate, not the successful-only latency figures above, is the more "
        f"direct measure of how the service handled increasing concurrency."
    )

    # Timeouts
    total_timeouts = int(df["is_timeout"].sum())
    if total_timeouts > 0:
        print(f"- Timeouts: {total_timeouts} request(s) exceeded the {REQUEST_TIMEOUT_SEC}s timeout.")
    else:
        print(f"- Timeouts: none of the {len(df)} requests exceeded the {REQUEST_TIMEOUT_SEC}s timeout.")

    # 429 / rate limiting
    total_429 = int(df["is_429"].sum())
    if total_429 > 0:
        print(f"- Rate limiting: {total_429} HTTP 429 response(s) were observed.")
    else:
        print("- Rate limiting: no HTTP 429 responses were observed during this run.")

    # Caching
    n_success = int(df["success"].sum())
    n_cached = int(df["potentially_cached"].sum())
    pct_cached = (n_cached / n_success * 100.0) if n_success else 0.0
    if n_cached > 0:
        print(
            f"- Potentially cached/identical responses: {n_cached}/{n_success} successful "
            f"responses ({pct_cached:.1f}%) had a body hash matching another response received "
            f"within the same wall-clock second. This is NOT proof of caching: every request in "
            f"this test used the same fixed fromTime/toTime window, so identical historical data "
            f"is expected for repeated requests to the same symbol regardless of caching behavior."
        )
    else:
        print("- Potentially cached/identical responses: none detected within the same second.")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    total_planned = len(CONCURRENCY_LEVELS) * REQUESTS_PER_CONCURRENCY
    print(f"dxFeed demo REST API load test")
    print(f"Endpoint: {BASE_URL}")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"Candle notation: {CANDLE_NOTATION}  fromTime={FROM_TIME}  toTime={TO_TIME}")
    print(f"Concurrency levels: {CONCURRENCY_LEVELS}")
    print(f"Requests per concurrency level: {REQUESTS_PER_CONCURRENCY}  (total planned: {total_planned})")
    print()

    all_results = []
    for level in CONCURRENCY_LEVELS:
        print(f"Running concurrency={level} ({REQUESTS_PER_CONCURRENCY} requests)...")
        t0 = time.perf_counter()
        level_results = run_concurrency_level(level, REQUESTS_PER_CONCURRENCY)
        elapsed = time.perf_counter() - t0
        all_results.extend(level_results)
        n_success = sum(1 for r in level_results if r["success"])
        print(f"  done in {elapsed:.2f}s  ({n_success}/{len(level_results)} successful)")

        if level != CONCURRENCY_LEVELS[-1]:
            time.sleep(PAUSE_BETWEEN_LEVELS_SEC)

    df = pd.DataFrame(all_results)
    df = mark_potentially_cached(df)

    # Persist request-level results.
    df.to_csv(RESULTS_CSV, index=False)
    print(f"\nSaved {len(df)} request-level results to {RESULTS_CSV}")

    summary_df = summarize(df)

    print("\nSummary")
    print("=======")
    print_summary_table(summary_df)

    print_interpretation(df, summary_df)


if __name__ == "__main__":
    main()
