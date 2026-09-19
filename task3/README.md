# Task 3 — Trading Holiday Scraper

Automated pipeline for gathering and normalizing trading holiday schedules for a configurable year, demonstrated with the 2026 schedules
## Live Output

* **Google Sheet:** https://docs.google.com/spreadsheets/d/1wOl-QPo0cW7b4MsWxuSn4OAZkK1vDwDVxmFZ7f2Br4c
* **Google Drive CSV:** https://drive.google.com/file/d/1pc29kgS5YejzLG0HkabJuqkSLR7dnqhF/view

## Pipeline

```text
NASDAQ / NYSE / CME / OPRA
            ↓
       Scrapers / data sources
            ↓
      Common data structure
            ↓
   pandas normalization & sorting
            ↓
       holidays.csv
          ↙       ↘
 Google Sheets    Google Drive
```

Each exchange produces the same structure:

```python
{
    "exchange": "NASDAQ",
    "date": "January 1, 2026",
    "holiday": "New Year's Day"
}
```

This keeps the rest of the pipeline independent of the source-specific scraping logic.

## Exchange Coverage

| Exchange | Source method                          | Result  |
| -------- | -------------------------------------- | ------- |
| NASDAQ   | Live scraping                          | Working |
| NYSE     | Live scraping                          | Working |
| CME      | Official 2026 schedule / fallback data | Working |
| OPRA     | Official schedule / fallback data      | Working |

### Source-specific handling

**NASDAQ:** The page contained multiple tables and the holiday table used the column order `Holiday → Date → Market Status`. The scraper was adjusted accordingly.

**NYSE:** The 2026 column contains day/month values without a year. The scraper adds the configured year before parsing and filters placeholder values such as `—`.

**CME:** Direct HTTP requests were blocked by Akamai with `403 Forbidden`. A Playwright attempt was also blocked, and reproducing browser headers did not bypass the protection. Network inspection identified an internal trading-hours API, but it was also protected and required additional session/browser context. The pipeline therefore uses the officially published 2026 CME holiday schedule as fallback data.

**OPRA:** Requests to the official source were unreachable from the execution environment, including direct HTTP and browser tests. The 2026 schedule was therefore provided using the published schedule as fallback data.

## Google Integration

A Google service account is used for programmatic access to both Google Sheets and Google Drive.

The service account credentials are loaded from `credentials.json`, which is excluded from version control.

Because service accounts do not have their own Drive storage quota, the CSV file is created once in the target Drive folder and subsequently updated by file ID. The folder is shared with the service account with Editor access.

## Setup

### 1. Google Cloud

1. Create a Google Cloud project.
2. Enable:

   * Google Sheets API
   * Google Drive API
3. Create a service account and download its credentials.
4. Place `credentials.json` inside `task3/`.

### 2. Google Drive

Create/share the required folder and Google Sheet with the service account. Upload an initial `holidays.csv` file and configure its file ID.

### 3. Environment

```bash
cp task3/.env.example task3/.env
```

Configure:

```text
SHEET_ID=your_google_sheet_id
CSV_FILE_ID=your_csv_file_id
```

Install dependencies:

```bash
pip install requests beautifulsoup4 pandas gspread google-auth \
            google-api-python-client python-dotenv
```

Run:

```bash
python3 task3/scraper.py
```

## Design Decisions

* A single `YEAR` constant controls the target year.
* Each scraper returns the same normalized structure.
* Each scraper is isolated with error handling so one source failure does not stop the remaining pipeline.
* HTTP failures from live sources are surfaced instead of silently producing invalid data.
* Data is normalized and sorted with pandas before publication.
* `credentials.json` is excluded from Git.

## Known Limitations

* CME and OPRA currently use 2026 fallback data rather than live scraping because of source accessibility restrictions.
* Updating to a future year requires updating the fallback schedules unless live source access is implemented.
* The Drive CSV must pre-exist because of the service account storage limitation.
* End-to-end execution typically takes approximately 20–35 seconds, largely due to Google API operations.
