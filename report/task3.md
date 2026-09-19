# Task 3 — Trading Holiday Data Pipeline

## 1. Objective

Build an **automated batch pipeline** that collects 2026 trading holiday schedules for NASDAQ, NYSE, CME, and OPRA, normalizes them into a common schema, and publishes results to Google Sheets and Google Drive.

This is a batch collection/publication job, **not** a real-time streaming system.

**Live outputs:**

- [Google Sheet](https://docs.google.com/spreadsheets/d/1wOl-QPo0cW7b4MsWxuSn4OAZkK1vDwDVxmFZ7f2Br4c)
- [Google Drive CSV](https://drive.google.com/file/d/1pc29kgS5YejzLG0HkabJuqkSLR7dnqhF/view)

Implementation: [`task3/scraper.py`](../task3/scraper.py) · local output: [`task3/holidays.csv`](../task3/holidays.csv)

## 2. Architecture / Data Flow

```text
NASDAQ / NYSE / CME / OPRA
            ↓
   source scrapers / collectors
            ↓
   common list of dictionaries
            ↓
 pandas normalize / sort / clean
            ↓
        holidays.csv
         ↙         ↘
 Google Sheets   Google Drive CSV
```

Collection is separated from normalization and output so source-specific quirks do not leak into publication logic.

## 3. Data Model

Each exchange produces the same record shape:

```python
{
    "exchange": "NASDAQ",
    "date": "January 1, 2026",
    "holiday": "New Year's Day"
}
```

After pandas processing, dates are normalized to `YYYY-MM-DD` and rows are sorted by exchange and date before write/upload.

## 4. Exchange Source Handling

| Exchange | Approach | Result |
| -------- | -------- | ------ |
| NASDAQ | Live scraping | Working |
| NYSE | Live scraping | Working |
| CME | Official published 2026 schedule (fallback) | Working |
| OPRA | Official published schedule (fallback) | Working |

### NASDAQ

- Live scrape of the holiday schedule page
- First relevant table is the holiday schedule
- Columns: Holiday, Date, Market Status
- Date/holiday mapping corrected to match that column order

### NYSE

- Live scrape
- Columns: Holiday, 2026, 2027, 2028
- 2026 date cells lack a year; the configured `YEAR` is appended
- Em-dash placeholders are filtered out

### CME

Investigation summary:

1. Direct requests returned 403
2. Playwright produced `ERR_HTTP2_PROTOCOL_ERROR`
3. DevTools/network inspection identified an internal trading-hours API
4. Direct access to that API also returned 403
5. Official 2026 schedule used as fallback

**Safe conclusion:** Direct and browser-based access to the CME source/API was unsuccessful from the execution environment, so the official published 2026 schedule was used as a fallback.

No claim is made here about specific WAF internals, TLS fingerprinting mechanisms, or geo-blocking policies beyond the observed failures.

### OPRA

- Requests timed out
- `curl` over IPv4 timed out
- IPv6 could not resolve
- Browser access failed

**Safe conclusion:** The official OPRA source was inaccessible from the execution environment, so the published schedule was used as fallback.

## 5. Normalization

- Merge all exchange records into one list
- Convert dates with pandas (`format='mixed'`)
- Drop unparseable dates
- Format dates as `YYYY-MM-DD`
- Sort by `exchange`, then `date`
- Persist locally as `holidays.csv`

## 6. Google Sheets / Drive Integration

- Service account authenticates to Google Sheets and Google Drive APIs
- Credentials loaded from `credentials.json` (excluded from Git)
- Sheet updated in place via `SHEET_ID`
- Service accounts do not have normal Drive storage quota for creating new files
- Therefore a CSV was created/uploaded once manually; the folder was shared with the service account as Editor; the script updates the existing file by `CSV_FILE_ID`
- A Shared Drive / appropriate organizational storage setup would be a cleaner long-term solution

Configuration is via `task3/.env`:

```text
SHEET_ID=...
CSV_FILE_ID=...
```

## 7. Error Handling and Reliability

- `YEAR = 2026` centralizes the target year
- Live scrapers call `raise_for_status()` so HTTP failures surface
- Each scraper runs in its own `try/except` in `main()` — one exchange failing does not stop the others
- Common record interface isolates source failures from normalization/output
- Drive upload failures are caught and reported; the local CSV remains available

## 8. Setup and Execution

1. Google Cloud project with Drive API and Sheets API enabled
2. Service account + `credentials.json` in `task3/`
3. Share Drive folder / Sheet with the service account (Editor)
4. Pre-create the Drive CSV and set `CSV_FILE_ID`
5. Configure `task3/.env` from [`task3/.env.example`](../task3/.env.example)
6. Install dependencies (`requests`, `beautifulsoup4`, `pandas`, `gspread`, `google-auth`, `google-api-python-client`, `python-dotenv`)
7. Run: `python3 task3/scraper.py`

Supporting reviewer notes: [`task3/README.md`](../task3/README.md)

## 9. Limitations

- CME and OPRA use fallback data rather than live scrapes from the current execution environment
- Future years require manual fallback updates unless live access is implemented
- Google API operations add runtime
- Drive CSV output requires a pre-existing file ID because of service-account storage limits
- Batch pipeline only — not streaming / Kafka / continuous ingestion

## 10. Conclusion

The pipeline delivers a repeatable batch path from heterogeneous exchange sources to a shared schema and dual Google publication targets. NASDAQ and NYSE are collected live; CME and OPRA use published fallbacks after access failures from the execution environment. Isolation between scrapers, a common data interface, and credential exclusion from version control keep the design supportable for assessment and future year updates.
