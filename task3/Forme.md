# Task 3 — Trading Holiday Scraper

Automated pipeline that scrapes 2026 trading holiday schedules from four major exchanges, cleans and normalizes the data, and uploads it to Google Sheets and Google Drive.

## Live Output

- **Google Sheet**: [View here](https://docs.google.com/spreadsheets/d/1wOl-QPo0cW7b4MsWxuSn4OAZkK1vDwDVxmFZ7f2Br4c)
- **Google Drive CSV**: [View here](https://drive.google.com/file/d/1pc29kgS5YejzLG0HkabJuqkSLR7dnqhF/view)

---

## Architecture

python3 scraper.py
↓
4 scrapers run (NASDAQ, NYSE, CME, OPRA)
↓
results merged into single list of dicts
↓
pandas: normalize dates → sort → clean
↓
save holidays.csv locally
↓
Google Sheets API: update Sheet1
↓
Google Drive API: update holidays.csv in Drive

Each scraper returns the same standardized structure regardless of
how the data was obtained:

```python
{'exchange': 'NASDAQ', 'date': 'January 1, 2026', 'holiday': "New Year's Day"}
```

This common interface means the rest of the pipeline doesn't care
whether data came from live scraping or a hardcoded fallback.

---



## Exchange Coverage


| Exchange | Method        | Result                                             |
| -------- | ------------- | -------------------------------------------------- |
| NASDAQ   | Live scraping | ✓ Working                                          |
| NYSE     | Live scraping | ✓ Working                                          |
| CME      | Hardcoded     | Site protected by Akamai — see investigation below |
| OPRA     | Hardcoded     | Domain geo-blocked — see investigation below       |


---



## Scraping Investigation & Challenges



### NASDAQ — column order discovery

Initial assumption: date in col[0], holiday name in col[1].

Debug revealed the actual structure:

['Holiday', 'Date', 'Market Status']
["New Year's Day", 'January 1, 2026', 'Closed']

Fix: swap to `cols[1]` for date, `cols[0]` for holiday name.
The page has 4 tables — table[0] is the holiday schedule.

### NYSE — missing year in date string

NYSE table contains multiple years side by side:

['Holiday', '2026', '2027', '2028']
["New Year's Day", 'Thursday, January 1', 'Friday, January 1', ...]

The 2026 column (col[1]) only contains day and month — no year.
Without the year, pandas parsed dates as year 0001 (`1-01-01`).

Fix: append `, {YEAR}` to each date string before parsing.
Also filtered out `—` and `—*` where a holiday doesn't exist in a given year.

### CME — Full investigation

**Step 1: Direct HTTP request**

```python
requests.get('https://www.cmegroup.com/tools-information/holiday-calendar.html')
# Result: 403 Forbidden
```

CME uses Akamai bot protection. Returns 403 regardless of User-Agent headers.

**Step 2: Headless browser (Playwright)**

```python
page.goto('https://www.cmegroup.com/tools-information/holiday-calendar.html')
# Result: ERR_HTTP2_PROTOCOL_ERROR
```

Akamai detects headless Chromium at the TLS/HTTP2 level and blocks the connection entirely.

**Step 3: Network tab investigation**

Opened the page in a real browser with DevTools → Network → XHR.
The holiday calendar page redirects to:

[https://www.cmegroup.com/trading-hours.html](https://www.cmegroup.com/trading-hours.html)

Which calls an internal API:

GET [https://www.cmegroup.com/services/trading-hours-by-product](https://www.cmegroup.com/services/trading-hours-by-product)
?id=316,133,425,300,58,437,22,8478,5201,10191
&pageNumber=1&pageSize=999&sortAsc=true
&fromEventDate=2026-01-01&toEventDate=2026-12-31

**Step 4: Direct API call with browser headers**

```python
requests.get('https://www.cmegroup.com/services/trading-hours-by-product', 
             headers={full browser headers copied from DevTools})
# Result: 403 Forbidden
```

Akamai uses session cookies (`_abck`) and TLS fingerprinting tied to the
real browser session. Replicating headers alone is insufficient.

**Conclusion:** CME requires either a real authenticated browser session,
an Akamai bypass service, or an official CME data subscription.
Additionally, the API returns trading hours per product — not a clean
holiday calendar endpoint. It would require mapping product IDs to
holiday dates, which adds significant complexity for uncertain results.

Data hardcoded from CME's officially published 2026 holiday calendar.

### OPRA — Full investigation

**Step 1: Direct HTTP request**

requests.get('[https://www.optionsclearing.com/](https://www.optionsclearing.com/)...')

Result: Connection timeout

**Step 2: curl with different options**

```bash
curl -I --connect-timeout 15 https://www.optionsclearing.com
# Result: Connection timed out

curl -6 -I --connect-timeout 15 https://www.optionsclearing.com  
# Result: Could not resolve host
```

**Step 3: Browser test**
Attempted to open optionsclearing.com directly in browser.
Result: Site unreachable.

**Conclusion:** `optionsclearing.com` is geo-blocked at the DNS level
from Georgian IP addresses. The domain cannot be resolved at all —
this is not an HTTP-level block but a network-level block.
No technical workaround is possible without routing traffic through
a non-Georgian IP.

OPRA observes the same holidays as NYSE per their published schedule.
Data hardcoded with this justification documented.

---



## Google Integration



### Authentication

Used a Google Cloud service account rather than OAuth because:

- OAuth requires a browser login flow — not suitable for automated scripts
- Service accounts authenticate programmatically using a JSON key file
- Credentials loaded once, reused for both Sheets and Drive clients



### CSV Drive Upload Workaround

Google service accounts have zero Drive storage quota — they cannot
create new files. Updating existing files does not require quota.

**Workaround:**

1. Manually upload `holidays.csv` to the Drive folder once
2. Share the folder with the service account email as Editor
3. Script updates the existing file on each run

Google Workspace Shared Drives would solve this properly but require
a paid account.

---



## Setup



### 1. Google Cloud

- Create a project at console.cloud.google.com
- Enable Google Drive API and Google Sheets API
- Create a service account, download `credentials.json`
- Place `credentials.json` in `task3/`



### 2. Google Drive

- Create a folder in your Google Drive
- Share it with your service account email as Editor
- Create a Google Sheet inside the folder, note its ID from the URL
- Upload an empty `holidays.csv` to the folder, note its file ID



### 3. Environment variables

```bash
cp task3/.env.example task3/.env
```

Edit `task3/.env`:

SHEET_ID=your_google_sheet_id
CSV_FILE_ID=your_csv_file_id

### 4. Install dependencies

```bash
pip install requests beautifulsoup4 pandas gspread google-auth \
            google-api-python-client python-dotenv
```



### 5. Run

```bash
python3 task3/scraper.py
```

---



## Design Decisions

**YEAR = 2026 as a constant**
All date references use a single `YEAR` variable. Change one line to target a different year.

**raise_for_status() on live scrapers**
If a live site returns 4xx/5xx, an exception is raised and caught by
the main loop. Partial data from other exchanges is still collected.

**try/except per scraper**
One scraper failing doesn't stop the others. The pipeline collects
whatever data it can and reports errors inline.

**Common scraper interface**
Every scraper returns the same dict structure regardless of data source.
main() doesn't know or care whether data came from HTTP or hardcoded —
the pipeline stays clean.

**credentials.json excluded from version control**
Contains a private key. Listed in `.gitignore`.

---



## Known Limitations

- CME and OPRA data is hardcoded for 2026 — requires manual update for future years
- CME: protected by Akamai at multiple levels (HTTP, TLS, session cookies)
- OPRA: geo-blocked at DNS level from Georgian IPs
- Script takes ~20-35 seconds due to Google API latency
- CSV Drive upload requires the file to pre-exist (service account quota limitation)

