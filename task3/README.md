# Task 3 — Trading Holiday Data Pipeline

Automated **batch pipeline** for collecting, normalizing, and publishing 2026 trading holiday schedules for NASDAQ, NYSE, CME, and OPRA.

The pipeline collects data from live exchange sources where accessible, falls back to officially published schedules when a source cannot be accessed from the execution environment, normalizes all results into a common structure, and publishes the final dataset to Google Sheets and Google Drive.

## Final Report

See [`../report/task3.md`](../report/task3.md) for the consolidated assessment, investigation details, and conclusions.

## Live Output

* **Google Sheet:** [View here](https://docs.google.com/spreadsheets/d/1wOl-QPo0cW7b4MsWxuSn4OAZkK1vDwDVxmFZ7f2Br4c)
* **Google Drive CSV:** [View here](https://drive.google.com/file/d/1pc29kgS5YejzLG0HkabJuqkSLR7dnqhF/view)

---

## Architecture

```text
NASDAQ / NYSE / CME / OPRA
            ↓
      Scrapers / sources
            ↓
     Common data structure
            ↓
   pandas normalization
     dates → sorting → cleanup
            ↓
       holidays.csv
          ↙       ↘
 Google Sheets    Google Drive
```

Each exchange scraper returns the same normalized structure:

```python
{
    "exchange": "NASDAQ",
    "date": "January 1, 2026",
    "holiday": "New Year's Day"
}
```

This common interface keeps the rest of the pipeline independent of whether data came from live scraping or fallback data.

---

## Exchange Coverage

| Exchange | Source Method                          | Result  |
| -------- | -------------------------------------- | ------- |
| NASDAQ   | Live scraping                          | Working |
| NYSE     | Live scraping                          | Working |
| CME      | Official 2026 schedule / fallback      | Working |
| OPRA     | Official published schedule / fallback | Working |

### Source-specific handling

**NASDAQ**

The source page contains multiple tables. Investigation showed that the relevant holiday table uses the column order:

```text
Holiday → Date → Market Status
```

The scraper extracts the holiday name and date accordingly and uses the relevant holiday table.

**NYSE**

The holiday table contains multiple years:

```text
Holiday | 2026 | 2027 | 2028
```

The 2026 values contain the day and month but not the year. The scraper appends the configured `YEAR` before parsing and filters placeholder values such as `—`.

**CME**

Direct and browser-based access to the CME holiday source was unsuccessful from the execution environment. The underlying trading-hours API was also investigated but could not be accessed successfully.

The officially published 2026 CME holiday schedule is therefore used as fallback data.

**OPRA**

The official OPRA source was inaccessible from the execution environment after HTTP, `curl`, and browser access attempts. The exact cause of the connectivity failure was not conclusively established.

The published 2026 schedule is therefore used as fallback data.

For the detailed investigation and evidence, see [`../report/task3.md`](../report/task3.md).

---

## Google Integration

The pipeline uses a **Google Cloud service account** for programmatic access to Google Sheets and Google Drive.

### Authentication

The service account:

* authenticates without an interactive OAuth login;
* uses `credentials.json`;
* provides access to both Sheets and Drive APIs;
* is used by the pipeline for automated publication.

`credentials.json` is excluded from version control.

### Drive CSV handling

The execution environment's service-account setup could not create new Drive files using the service account's own storage quota.

The implemented workaround is:

1. Create/upload `holidays.csv` once in the target Drive folder.
2. Share the folder with the service account with Editor access.
3. Store the existing CSV's file ID.
4. Update that file on subsequent pipeline runs.

A Shared Drive or appropriate organizational storage setup would be a cleaner long-term solution.

---

## Setup

### 1. Google Cloud

1. Create a Google Cloud project.
2. Enable the **Google Sheets API** and **Google Drive API**.
3. Create a service account.
4. Download its credentials.
5. Place `credentials.json` inside `task3/`.

### 2. Google Drive

Create/share the required Drive folder and Google Sheet with the service account.

Create the initial `holidays.csv` file in the folder and record its file ID.

### 3. Environment Variables

```bash
cp task3/.env.example task3/.env
```

Configure:

```text
SHEET_ID=your_google_sheet_id
CSV_FILE_ID=your_csv_file_id
```

### 4. Install Dependencies

```bash
pip install requests beautifulsoup4 pandas gspread google-auth \
            google-api-python-client python-dotenv
```

### 5. Run

From the repository root:

```bash
python3 task3/scraper.py
```

---

## Design Decisions

**Single `YEAR` configuration**

All year-specific date handling uses the `YEAR` constant, allowing the target year to be changed centrally.

**Common scraper interface**

Every exchange scraper returns the same normalized dictionary structure. The publication layer therefore does not need to know where the data originated.

**Independent source handling**

Each scraper is isolated with error handling so that one inaccessible exchange does not prevent the remaining sources from being processed.

**HTTP failures are surfaced**

Live-source HTTP failures are not silently converted into valid-looking data. Failed sources are reported and handled through the configured fallback where available.

**Normalize before publishing**

Data is normalized and sorted with pandas before being written to the local CSV and published to Google Sheets/Drive.

**Secrets excluded from Git**

`credentials.json` and environment files containing configuration/secrets are excluded through `.gitignore`.

---

## Known Limitations

* CME and OPRA currently use published 2026 fallback schedules rather than live scraping because their sources were inaccessible from the execution environment.
* Future years require updated fallback schedules unless live source access is implemented.
* The Drive CSV must be created once before the pipeline can update it in this setup.
* End-to-end execution typically takes approximately 20–35 seconds, largely due to Google API operations.
* This is a **batch pipeline**, not a real-time streaming system.

---

## Supporting Material

| File                                       | Role                                              |
| ------------------------------------------ | ------------------------------------------------- |
| [`scraper.py`](./scraper.py)               | Pipeline implementation                           |
| [`holidays.csv`](./holidays.csv)           | Local normalized output                           |
| [`Forme.md`](./Forme.md)                   | Detailed investigation notes and working material |
| [`../report/task3.md`](../report/task3.md) | Final assessment report                           |
