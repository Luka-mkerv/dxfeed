# Task 3 — Exchange Holiday Scraper

## 1. Objective

The objective of Task 3 is to build a batch pipeline that collects 2026 trading holiday information for NASDAQ, NYSE, CME, and OPRA, normalizes the results into a common structure, stores the resulting dataset locally, and publishes it to Google Sheets and an existing Google Drive CSV.

The implementation uses live exchange sources where practical and source-specific handling where an exchange does not provide the required data through a directly accessible endpoint.

The final validated dataset contains **42 records**:

* CME: 10
* NASDAQ: 12
* NYSE: 10
* OPRA: 10

---

## 2. Architecture

The pipeline follows a source-specific scraping → common normalization → publishing architecture.

```text
                    ┌─────────────┐
                    │   NASDAQ    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │     NYSE    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │     CME     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │     OPRA    │
                    └──────┬──────┘
                           │
                           ▼
                Source-specific parsing
                           │
                           ▼
                  Common record format
                           │
                           ▼
                 Pandas normalization
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        Local CSV    Google Sheets   Drive CSV
```

Each scraper returns records using the same structure:

```python
{
    "exchange": "CME",
    "date": "January 1, 2026",
    "holiday": "New Year's Day"
}
```

This separates source-specific parsing from common data processing and publishing.

---

# 3. Exchange Sources

## 3.1 NASDAQ

NASDAQ is collected through HTTP requests and HTML parsing with BeautifulSoup.

The source contains multiple tables, so the scraper identifies the relevant holiday table rather than assuming that the first table on the page is the required dataset.

The source table uses the following relevant ordering:

```text
Holiday → Date → Market Status
```

The scraper extracts the holiday name and date and converts the results into the common record structure.

NASDAQ produced **12 records** in the final dataset.

---

## 3.2 NYSE

NYSE is also collected through HTTP requests and HTML parsing.

The NYSE source contains a table covering multiple years. For the 2026 section, dates are represented without an explicit year, so the scraper appends the configured target year:

```text
2026
```

Placeholder values such as `—` are ignored.

### Source annotation issue

The NYSE source also contains annotations attached to some dates. Examples include:

```text
Friday, July 3 (Independence Day observed), 2026
Thursday, November 26***, 2026
Friday, December 25****, 2026
```

Passing these strings directly to the common pandas date parser can result in `NaT`.

This initially caused three valid NYSE records to disappear during the global validation step because invalid parsed dates were removed with `dropna()`.

The issue was fixed at the source boundary rather than by weakening global validation.

A NYSE-specific cleaner removes:

* parenthetical annotations
* `*` markers
* excess whitespace
* trailing commas

Conceptually:

```python
def _clean_nyse_date(date_raw: str) -> str:
    cleaned = re.sub(r'\([^)]*\)', '', date_raw)
    cleaned = cleaned.replace('*', '')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().rstrip(',')
    return cleaned
```

The cleaned value is then passed into the normal date pipeline.

This preserves the global validation rule while handling the known format of the NYSE source.

NYSE produced **10 records** in the final dataset.

---

# 4. CME Investigation and Implementation

CME required the most investigation because the normal HTTP scraping approach was not sufficient.

## 4.1 Direct HTTP attempt

The CME trading-hours page was initially accessed using normal HTTP requests.

The request returned:

```text
HTTP 403
```

This prevented conventional `requests` + BeautifulSoup scraping.

## 4.2 Internal API investigation

The page's network traffic was inspected to identify whether the holiday data came from an internal API.

An internal trading-hours endpoint was identified, but direct access to that endpoint also resulted in:

```text
HTTP 403
```

Therefore, switching from the visible page to the underlying API did not solve the access problem.

## 4.3 Initial Playwright attempt

Browser automation was then tested with Playwright.

The first implementation encountered:

```text
ERR_HTTP2_PROTOCOL_ERROR
```

This showed that simply replacing `requests` with a browser was not sufficient in the original configuration.

## 4.4 Additional investigation

The `exchange-calendars` Python package was evaluated as another possible source.

Although CME calendars were available, they did not reproduce the complete 2026 holiday dataset required for this task with sufficient fidelity.

It was therefore not used as the production source.

A browser-based diagnostic agent was also used to inspect the live CME page. It was able to navigate the page, handle the cookie banner, locate the live:

```text
2026 CME Globex Trading Schedule
```

heading, and extract the relevant table.

The agent was used only as a diagnostic investigation tool. It is **not** a runtime dependency of the production scraper.

## 4.5 Clean Playwright reproduction

A separate clean Playwright + Chromium experiment was then created outside the main dxFeed project to determine whether the browser approach itself was viable.

That reproduction successfully:

* launched Chromium
* loaded the CME page
* received HTTP 200
* located the 2026 trading schedule
* located the relevant table
* captured the page successfully

This isolated the problem from the production project's Python code and demonstrated that Playwright + Chromium could be used reliably with the correct browser configuration.

## 4.6 Production implementation

The production scraper uses Playwright with Chromium.

The working configuration uses:

```text
headless=False
--headless=new
```

The `--headless=new` flag provides the newer Chromium headless implementation while still allowing the job to run without a visible browser window.

The scraper reads the live CME Globex trading schedule rather than embedding a manually maintained list of dates.

### Multi-day holiday windows

CME's table represents holidays as trading windows rather than simply providing one date per holiday.

For example, a holiday may be represented as a range such as:

```text
December 24–26
```

The scraper converts these windows into a canonical holiday date for the requested year.

The final 2026 CME dates are:

```text
2026-01-01
2026-01-19
2026-02-16
2026-04-03
2026-05-25
2026-06-19
2026-07-03
2026-09-07
2026-11-26
2026-12-25
```

The implementation derives these values from the live table rather than hardcoding them.

CME produced **10 records** in the final dataset.

---

# 5. OPRA

The official OPRA website is accessible from the execution environment.

However, the current OPRA document library does not contain a dedicated 2026 Holiday Schedule document.

Because the required 2026 regular full-day holiday information was not available as a current dedicated document, the implementation uses a verified static 2026 dataset based on the available official schedule/reference information.

This is intentionally different from claiming that the OPRA website itself was inaccessible.

The fallback covers regular full-day holidays and does not attempt to model:

* early closes
* exceptional closures
* future schedule changes

OPRA produced **10 records** in the final dataset.

---

# 6. Data Normalization

After all source-specific scrapers finish, their results are combined into one pandas DataFrame.

The general pipeline is:

```text
Scraper results
      │
      ▼
DataFrame
      │
      ▼
Parse dates
      │
      ▼
Remove invalid dates
      │
      ▼
Format as YYYY-MM-DD
      │
      ▼
Sort by exchange/date
      │
      ▼
Publish
```

Date parsing uses:

```python
pd.to_datetime(..., format="mixed")
```

Invalid dates are converted to `NaT` and removed before publication.

The NYSE-specific cleaning described above ensures that legitimate annotated dates are cleaned before reaching this global validation stage.

The final date format is:

```text
YYYY-MM-DD
```

Records are sorted by:

1. exchange
2. date

---

# 7. Error Handling

Each exchange scraper is handled independently.

Conceptually:

```text
NASDAQ failure ──┐
NYSE failure   ──┤
CME failure    ──┼──> Other sources continue
OPRA failure   ──┘
```

This prevents one problematic source from automatically terminating the entire collection process.

Source-specific handling is used where required:

* NASDAQ: HTTP/HTML parsing
* NYSE: HTTP/HTML parsing plus date annotation cleaning
* CME: Playwright/Chromium browser extraction
* OPRA: verified static fallback

The common normalization stage remains strict. Invalid dates are not silently published.

---

# 8. Google Sheets and Google Drive Integration

The pipeline uses a Google service account for external publishing.

Authentication is performed using:

```python
Credentials.from_service_account_file(...)
```

The credentials are then passed to the Google Sheets client.

The required Google APIs are used for:

* updating the Google Sheet
* locating/updating the existing Drive CSV

The implementation updates an existing Drive CSV rather than relying on service-account file creation.

This avoids the service-account Drive quota/restriction encountered during development.

Secrets are kept outside the source code.

---

# 9. Setup

Create the virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

This repository does not include a `requirements.txt`. Install the packages imported by `task3/scraper.py`, then install Chromium for Playwright:

```bash
pip install requests beautifulsoup4 pandas gspread google-auth google-api-python-client python-dotenv playwright
playwright install chromium
```

Required configuration includes:

```text
task3/credentials.json
task3/.env          # copy from task3/.env.example
```

The environment configuration provides `SHEET_ID` and `CSV_FILE_ID` (see `task3/.env.example`).

The scraper is then executed with:

```bash
python task3/scraper.py
```

The execution performs the complete pipeline:

```text
Scrape
  ↓
Normalize
  ↓
Validate
  ↓
Write holidays.csv
  ↓
Update Google Sheet
  ↓
Update Drive CSV
```

---

# 10. Validation

The final production run was validated after correcting the NYSE annotation issue.

The resulting counts are:

| Exchange  | Records |
| --------- | ------: |
| CME       |      10 |
| NASDAQ    |      12 |
| NYSE      |      10 |
| OPRA      |      10 |
| **Total** |  **42** |

The important validation point is that the three previously lost NYSE records are now present:

```text
2026-07-03 — Independence Day observed
2026-11-26 — Thanksgiving Day
2026-12-25 — Christmas Day
```

The resulting dataset was successfully written to:

```text
holidays.csv
```

and the Google Sheet and existing Google Drive CSV were successfully updated.

---

# 11. Design Decisions

## Common interface

All exchange-specific functions return the same record structure.

This makes the downstream pipeline independent of the source implementation.

## Source-specific parsing

Parsing quirks are handled as close to the source as possible.

For example, NYSE annotation cleaning is performed inside `scrape_nyse()` rather than weakening the global date-validation logic.

## Strict normalization

The common pandas pipeline validates dates before publication.

This provides a final safety net against malformed source data.

## Independent source failures

A failure in one exchange does not automatically terminate processing of the other exchanges.

## Browser automation only where necessary

Playwright is used for CME because conventional HTTP access was blocked and the live data could not be reliably obtained through the direct endpoint.

The other sources remain HTTP-based.

## No runtime AI dependency

An AI browser agent was used during CME investigation to help diagnose the live page structure.

The production scraper does not depend on an LLM or browser agent.

## No hardcoded CME holiday list

CME dates are derived from the live trading-hours table.

## Secrets outside source code

Credentials and Google resource identifiers are kept in configuration rather than embedded directly in the scraper.

---

# 12. Known Limitations

### OPRA

The current implementation uses a static verified 2026 regular full-day dataset because a dedicated 2026 Holiday Schedule is not currently present in the official OPRA document library.

The fallback does not model early closes or exceptional closures.

### CME browser dependency

CME scraping depends on Playwright and Chromium.

Browser startup, page loading, and browser/network behavior introduce more operational complexity than a normal HTTP request.

### Google Drive creation

The implementation assumes that the target Drive CSV already exists.

Creating new Drive files using the service-account setup encountered quota/account restrictions during development.

### Batch architecture

The scraper is currently designed as a batch job. It does not continuously monitor exchange schedules for changes.

---

# 13. Conclusion

The completed pipeline collects, normalizes, validates, and publishes 2026 trading holiday data for four exchanges.

The final validated output contains:

```text
CME     10
NASDAQ  12
NYSE    10
OPRA    10
---------------
Total   42
```

The implementation combines conventional HTTP scraping, source-specific parsing, browser automation for CME, a documented OPRA fallback, centralized pandas normalization, and Google publishing.

The main implementation challenge was CME access, which required investigation beyond ordinary HTTP requests. The main data-quality issue was the presence of annotations in NYSE date strings, which was resolved at the source-parsing boundary while preserving strict global validation.
