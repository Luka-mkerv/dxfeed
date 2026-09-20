# Task 3 — Trading Holiday Data Pipeline

Automated batch pipeline that collects 2026 trading holiday data for NASDAQ, NYSE, CME, and OPRA, normalizes the results, writes a local CSV, and publishes the data to Google Sheets and an existing Google Drive CSV.

## Final Report

Detailed implementation decisions, source investigations, validation, and limitations are documented in:

[`../report/task3.md`](../report/task3.md)

## Live Output

The pipeline publishes the final dataset to the configured Google Sheet and Google Drive CSV.

## Architecture

```text
NASDAQ ──┐
NYSE   ──┤
CME    ──┼──> Source-specific scrapers
OPRA   ──┘
                │
                ▼
        Common record format
                │
                ▼
          Pandas normalization
                │
                ├──> holidays.csv
                │
                ├──> Google Sheets
                │
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

This keeps source-specific parsing separate from common validation and publishing logic.

## Exchange Coverage

| Exchange | Source method                  | Status                         |
| -------- | ------------------------------ | ------------------------------ |
| NASDAQ   | Live HTTP + BeautifulSoup      | Live scraping                  |
| NYSE     | Live HTTP + BeautifulSoup      | Live scraping                  |
| CME      | Playwright + Chromium          | Live browser scraping          |
| OPRA     | Official source/reference data | Verified 2026 fallback dataset |

### Source-specific handling

**NASDAQ**

The scraper processes the relevant holiday table and handles the source's column ordering (`Holiday → Date → Market Status`). The resulting records are normalized into the common schema.

**NYSE**

The source contains a 2026/2027/2028 table where 2026 dates are represented without the year. The scraper appends `2026` and filters out placeholder values such as `—`.

Some NYSE dates also contain source annotations, for example:

```text
Friday, July 3 (Independence Day observed), 2026
Thursday, November 26***, 2026
Friday, December 25****, 2026
```

These annotations can prevent direct date parsing. A NYSE-specific cleaner removes parenthetical annotations and `*` markers before the data reaches the common pandas normalization stage.

**CME**

Direct HTTP/API access returned `403`, and an earlier Playwright approach encountered an HTTP/2 protocol error. A separate clean Playwright + Chromium reproduction successfully loaded the live CME trading-hours table.

The production scraper therefore uses Playwright with Chromium and the newer headless mode (`--headless=new`). Multi-day Globex holiday windows are converted into one canonical 2026 holiday date.

No hardcoded CME holiday list is used.

**OPRA**

The official OPRA website is accessible, but the current document library does not contain a 2026 Holiday Schedule. The scraper therefore uses a verified static 2026 dataset for regular full-day holidays based on the available official schedule/reference information.

This fallback does not attempt to model early closes or exceptional closures.

## Google Integration

A Google service account is used for publishing.

Required environment variables (see [`.env.example`](./.env.example)):

```text
SHEET_ID
CSV_FILE_ID
```

These match `task3/scraper.py` (`os.getenv('SHEET_ID')`, `os.getenv('CSV_FILE_ID')`).

The service account credentials are loaded from:

```text
task3/credentials.json
```

Google Sheets is updated through `gspread` using `SHEET_ID`.

The Drive CSV is updated through the Google Drive API using `CSV_FILE_ID` (an existing Drive **file** ID, not a folder ID).

The implementation updates that existing Drive CSV rather than creating a new Drive file, because service-account Drive file creation can fail due to quota/account restrictions.

Credentials and secrets are excluded from the repository.

## Setup

Create and activate the virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

This repository does not include a `requirements.txt`. Install the packages imported by `task3/scraper.py`, then install Chromium for Playwright:

```bash
pip install requests beautifulsoup4 pandas gspread google-auth google-api-python-client python-dotenv playwright
playwright install chromium
```

Configure:

```text
task3/credentials.json
task3/.env          # copy from task3/.env.example
```

Then run from the repository root:

```bash
python task3/scraper.py
```

The pipeline will:

1. Scrape each exchange.
2. Normalize and validate dates.
3. Save `task3/holidays.csv`.
4. Update the Google Sheet.
5. Update the existing Google Drive CSV.

## Validation / Final Output

The final validated dataset contains:

| Exchange  | Records |
| --------- | ------: |
| CME       |      10 |
| NASDAQ    |      12 |
| NYSE      |      10 |
| OPRA      |      10 |
| **Total** |  **42** |

The final run successfully updated both Google Sheets and the Google Drive CSV.

## Design Decisions

* One target year (`2026`) is used throughout the pipeline.
* All exchange scrapers return the same record structure.
* Source-specific parsing is kept inside each scraper.
* Common date validation is performed centrally with pandas.
* Invalid dates are removed before publishing.
* One source failing does not automatically prevent the other exchanges from being processed.
* Browser automation is used only where conventional HTTP access is insufficient.
* No LLM or browser agent is required at runtime.
* Secrets are stored outside source code.
* Data is normalized before being written to external systems.

## Known Limitations

* OPRA currently relies on a verified static 2026 regular full-day holiday dataset because a 2026 schedule is not currently present in the official document library.
* The CME scraper depends on Playwright and Chromium and is therefore more operationally complex than the HTTP-based scrapers.
* CME browser execution can be affected by browser/network environment differences.
* The Google Drive integration assumes the target CSV already exists.
* End-to-end runtime includes CME browser startup/page loading and Google API operations, so it is higher than a requests-only scraper.
* The pipeline is designed as a batch job rather than a continuously running service.

## Supporting Material

```text
task3/
├── scraper.py
├── holidays.csv
├── .env.example
└── README.md

report/
└── task3.md
```
