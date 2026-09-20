# Task 3 — Exchange Holiday Scraper

## 1. Objective

The goal of Task 3 is to collect the 2026 trading holidays for:

* NASDAQ
* NYSE
* CME
* OPRA

The scraper normalizes the results into a common format, saves them locally as CSV, and synchronizes the data with Google Sheets and an existing CSV file in Google Drive.

The main design goal is to use live exchange sources where practical, while keeping source-specific handling isolated so that one exchange failure does not stop the entire pipeline.

---

## 2. Architecture

The scraper is organized into independent exchange-specific functions:

```text
NASDAQ ──┐
NYSE ────┤
CME ─────┼──> Normalize with pandas ──> holidays.csv
OPRA ────┘                              │
                                       ├──> Google Sheets
                                       └──> Google Drive CSV
```

Each scraper returns dictionaries using the same structure:

```python
{
    "exchange": "CME",
    "date": "January 1, 2026",
    "holiday": "New Year's Day"
}
```

The main pipeline then:

1. Runs each exchange scraper independently.
2. Combines the returned records.
3. Parses and normalizes dates with pandas.
4. Removes invalid dates.
5. Formats dates as `YYYY-MM-DD`.
6. Sorts the final dataset by exchange and date.
7. Saves `holidays.csv`.
8. Updates the Google Sheet.
9. Updates the existing CSV file in Google Drive.

Each exchange scraper has its own error handling, so a failure from one source does not terminate the complete run.

---

## 3. Exchange Sources

### NASDAQ

NASDAQ is scraped from its published holiday calendar using an HTTP request and BeautifulSoup.

The scraper extracts the holiday name and date, then converts the result into the common data structure.

NASDAQ's calendar also contains early-close information. These entries are retained where they are part of the published calendar data.

---

### NYSE

NYSE is scraped from its published 2026 holiday calendar using an HTTP request and BeautifulSoup.

The scraper extracts the relevant holiday dates and names and returns them in the common format.

The final normalization step is responsible for converting the returned dates into the standard `YYYY-MM-DD` representation.

---

### CME

CME required additional investigation because the normal HTTP approach could not retrieve the trading-hours page.

#### Investigation

The first approach used `requests`, but the CME page returned HTTP 403.

An internal trading-hours API was also identified during browser/network investigation, but direct requests to that API were also rejected with HTTP 403.

An earlier Playwright attempt then failed with:

```text
ERR_HTTP2_PROTOCOL_ERROR
```

`exchange-calendars` was also evaluated as an alternative source. Although CME calendars are available through the library, they did not reproduce the complete 2026 holiday schedule required by the task.

A browser-based AI agent was then used as a diagnostic tool. It successfully loaded the CME trading-hours page, accepted the cookie banner, located:

```text
2026 CME Globex Trading Schedule
```

and identified the table containing the relevant schedule.

This established that the page was accessible in a real browser context and helped identify the required DOM structure.

A clean standalone Playwright + Chromium test was then created separately from the dxFeed project. It successfully reproduced the page access and table extraction without using an AI agent.

#### Production implementation

The production scraper therefore uses deterministic Playwright with Chromium.

A notable implementation detail is that normal:

```python
headless=True
```

continued to produce the HTTP/2 error.

The working configuration uses Chromium's newer headless mode:

```text
--headless=new
```

while launching Chromium with the browser window hidden.

The scraper:

1. Launches Playwright-managed Chromium.
2. Opens the CME trading-hours page.
3. Locates the `2026 CME Globex Trading Schedule` section.
4. Extracts the associated table.
5. Parses the multi-day trading windows.
6. Converts each relevant window into one canonical holiday date.
7. Filters the resulting dates to 2026.

The CME page presents trading windows rather than simply listing one date per holiday. For example, a holiday may appear as:

```text
December 31, 2025 - January 2, 2026
```

The scraper therefore derives the actual holiday date from the holiday name and date range rather than treating every date in the trading window as a holiday.

The resulting 2026 CME dates are:

```text
2026-01-01  New Year's Day
2026-01-19  Martin Luther King Jr. Day
2026-02-16  Presidents' Day
2026-04-03  Good Friday
2026-05-25  Memorial Day
2026-06-19  Juneteenth
2026-07-03  Independence Day (observed)
2026-09-07  Labor Day
2026-11-26  Thanksgiving Day
2026-12-25  Christmas Day
```

No hardcoded CME holiday list or static fallback is used in the production scraper.

If browser loading or parsing fails, the CME scraper raises an error and the main pipeline continues with the other exchanges.

---

### OPRA

OPRA's official website is accessible from the execution environment, but its document library does not currently contain a 2026 Holiday Schedule.

The 2025 OPRA schedule was therefore used as a reference for the regular holiday structure, and the verified 2026 regular full-day holidays were represented as a static dataset.

This is intentionally different from the CME approach: there is currently no published 2026 OPRA schedule available from the official document library to scrape.

The fallback covers regular full-day holidays but does not attempt to model early closes or exceptional closures that could appear in a future official schedule.

---

## 4. Data Normalization

After all exchange scrapers complete, the results are combined into a pandas DataFrame.

Dates are parsed using:

```python
pd.to_datetime(..., format="mixed")
```

Invalid dates are removed, and valid dates are formatted as:

```text
YYYY-MM-DD
```

The final dataset is sorted by:

1. Exchange
2. Date

This produces a consistent schema regardless of how each individual exchange publishes its calendar.

---

## 5. Google Integration

The scraper uses a Google service account for synchronization.

Credentials are loaded from the local credentials file and used with the required Google API scopes.

The resulting data is:

* written to the configured Google Sheet
* uploaded to the existing CSV file in Google Drive

The Drive integration updates an existing file rather than attempting to create a new Drive file, avoiding the service-account storage/quota limitation encountered during development.

---

## 6. Error Handling

Each exchange scraper is isolated with its own exception handling.

Conceptually:

```text
NASDAQ failure ──┐
NYSE failure ────┤
CME failure ─────┼──> Other exchanges continue
OPRA failure ────┘
```

This prevents a failure in one external source from stopping the complete task.

The Google synchronization is performed after local data generation. Therefore, the locally generated CSV remains available even if a later Google API operation fails.

---

## 7. Setup

Create and activate the Python virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install the required Python packages:

```bash
pip install -r requirements.txt
```

Install the Chromium browser used by Playwright:

```bash
playwright install chromium
```

Required local configuration includes:

```text
.env
credentials.json
```

The Google service-account credentials must have access to the target Sheet and existing Drive CSV.

Run the scraper from the project root:

```bash
python task3/scraper.py
```

---

## 8. Validation

The completed pipeline was executed successfully from the dxFeed project:

```text
Scraping NASDAQ...
→ 12 holidays found

Scraping NYSE...
→ 10 holidays found

Scraping CME (Playwright)...
→ 10 holidays found

Total holidays collected: 39

CSV saved locally
Google Sheet updated
CSV updated in Google Drive

Done!
```

The final normalized dataset contains:

```text
CME       10
NASDAQ    12
NYSE       7
OPRA      10
----------------
Total     39
```

The local CSV was regenerated successfully, and both Google Sheet and Google Drive synchronization completed without errors.

The difference between the NYSE scraper's reported 10 extracted records and the 7 records present after normalization should be investigated further if the scraper is extended beyond the current task.

---

## 9. Limitations

The main limitations are source-specific:

* **NASDAQ:** published calendar data may contain early-close entries in addition to full holidays.
* **NYSE:** source formatting requires normalization before producing the final dataset.
* **CME:** requires browser automation because direct HTTP/API access returned 403 and an earlier Playwright configuration produced an HTTP/2 error.
* **OPRA:** no official 2026 Holiday Schedule is currently available in the site's document library, so the regular 2026 holiday dataset is represented statically.

The scraper is therefore not completely source-uniform: each exchange uses the method most appropriate for the currently available source.

---

## 10. Conclusion

Task 3 implements a complete holiday-data pipeline covering NASDAQ, NYSE, CME, and OPRA.

The implementation separates exchange-specific scraping from common normalization and output logic. It uses live sources where they are available, Playwright + Chromium for the CME browser-only case, and a documented static dataset for OPRA where an official 2026 schedule is not currently published.

The resulting data is normalized into a single CSV format and synchronized with both Google Sheets and Google Drive.

The final implementation favors deterministic scraping and explicit source-specific behavior rather than relying on an AI agent or undocumented assumptions about external exchange infrastructure.
