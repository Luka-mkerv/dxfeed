# Task 3 — Exchange Holiday Scraper

## Overview

This task collects the 2026 trading holidays for:

* NASDAQ
* NYSE
* CME
* OPRA

The scraper normalizes all exchange data into a common format, saves it locally as `holidays.csv`, and synchronizes the result with Google Sheets and an existing CSV file in Google Drive.

The implementation uses exchange-specific scrapers because each source exposes its calendar differently.

For the detailed investigation and reasoning behind the source choices, see:

```text
report/task3.md
```

---

## Architecture

```text
NASDAQ ──┐
NYSE ────┤
CME ─────┼──> pandas normalization ──> holidays.csv
OPRA ────┘                              │
                                       ├──> Google Sheets
                                       └──> Google Drive CSV
```

Each scraper returns the same structure:

```python
{
    "exchange": "CME",
    "date": "January 1, 2026",
    "holiday": "New Year's Day"
}
```

The main pipeline then:

1. Runs all exchange scrapers.
2. Combines the results.
3. Normalizes and validates dates with pandas.
4. Sorts the final dataset.
5. Saves `holidays.csv`.
6. Updates Google Sheets.
7. Updates the existing Google Drive CSV.

A failure in one exchange scraper does not stop the other exchanges from being processed.

---

## Exchange Sources

### NASDAQ

Uses HTTP requests and BeautifulSoup to scrape the published NASDAQ holiday calendar.

Early-close entries are retained when provided by the source.

### NYSE

Uses HTTP requests and BeautifulSoup to scrape the published NYSE holiday calendar.

The extracted dates are normalized with pandas before being written to the final dataset.

### CME

CME requires browser automation.

Direct HTTP requests and the discovered internal API returned HTTP 403. An earlier Playwright configuration also produced an `ERR_HTTP2_PROTOCOL_ERROR`.

During investigation, a browser-based AI agent was used only as a diagnostic tool. It successfully loaded the CME page, located the `2026 CME Globex Trading Schedule` section, and identified the relevant table.

A clean standalone Playwright + Chromium environment was then used to reproduce the result without an AI agent.

The production scraper therefore uses deterministic Playwright + Chromium.

An important implementation detail is that standard Playwright `headless=True` continued to fail, while Chromium's newer headless mode worked:

```text
--headless=new
```

The scraper extracts the live 2026 CME trading schedule and converts the multi-day Globex trading windows into canonical holiday dates.

No hardcoded CME holiday list is used.

For the complete CME investigation, see `report/task3.md`.

### OPRA

The official OPRA website is accessible, but its document library does not currently contain a 2026 Holiday Schedule.

The implementation therefore uses a verified static dataset for the regular 2026 full-day holidays.

This does not attempt to model future early closes or exceptional closures that could be included in an official 2026 schedule if one is published later.

---

## Data Normalization

The raw results are combined into a pandas DataFrame.

Dates are parsed using:

```python
pd.to_datetime(..., format="mixed")
```

Invalid dates are removed and valid dates are formatted as:

```text
YYYY-MM-DD
```

The final data is sorted by exchange and date.

---

## Google Integration

The scraper uses a Google service account to synchronize the generated data.

It:

* updates the configured Google Sheet
* updates the existing CSV file in Google Drive

The Drive operation updates an existing file rather than creating a new one.

Required credentials:

```text
credentials.json
```

Required configuration:

```text
.env
```

The service account must have access to the target Google Sheet and existing Drive CSV.

---

## Setup

Create the virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Install the Chromium browser required by Playwright:

```bash
playwright install chromium
```

Run the scraper from the project root:

```bash
python task3/scraper.py
```

---

## Output

The scraper produces:

```text
task3/holidays.csv
```

and synchronizes the same normalized dataset with:

* Google Sheets
* Google Drive CSV

A successful run currently produces 39 normalized records:

```text
CME       10
NASDAQ    12
NYSE       7
OPRA      10
----------------
Total     39
```

---

## Error Handling

Exchange scrapers are isolated from each other.

If one external source fails:

```text
NASDAQ ──┐
NYSE ────┤
CME ─────┼──> remaining exchanges continue
OPRA ────┘
```

Local CSV generation occurs before Google synchronization, so the collected data remains available locally even if a Google API operation fails.

---

## Project Structure

```text
dxfeed/
├── task3/
│   ├── scraper.py
│   ├── holidays.csv
│   └── README.md
│
└── report/
    └── task3.md
```

`README.md` provides the quick technical overview.

`report/task3.md` contains the detailed implementation decisions, source investigation, validation, and limitations.
