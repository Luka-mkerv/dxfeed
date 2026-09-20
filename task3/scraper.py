import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv
import os
import re
from datetime import date, timedelta
from playwright.sync_api import sync_playwright

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), 'credentials.json')
YEAR = 2026

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
SHEET_ID = os.getenv('SHEET_ID')
CSV_FILE_ID = os.getenv('CSV_FILE_ID')

def get_clients():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    sheets_client = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return sheets_client, drive_service


def scrape_nasdaq():
    print("Scraping NASDAQ...")
    url = "https://www.nasdaq.com/market-activity/stock-market-holiday-schedule"
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    holidays = []
    tables = soup.find_all('table')
    if tables:
        rows = tables[0].find_all('tr')[1:]
        for row in rows:
            cols = row.find_all(['td', 'th'])
            if len(cols) >= 2:
                holidays.append({
                    'exchange': 'NASDAQ',
                    'date': cols[1].text.strip(),
                    'holiday': cols[0].text.strip()
                })
    return holidays


def scrape_nyse():
    print("Scraping NYSE...")
    url = "https://www.nyse.com/markets/hours-calendars"
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    holidays = []
    table = soup.find('table')
    if table:
        rows = table.find_all('tr')[1:]
        for row in rows:
            cols = row.find_all(['td', 'th'])
            if len(cols) >= 2:
                holiday_name = cols[0].text.strip()
                date_raw = cols[1].text.strip()
                if date_raw and date_raw != '—' and date_raw != '—*':
                    holidays.append({
                        'exchange': 'NYSE',
                        'date': f"{date_raw}, {YEAR}",
                        'holiday': holiday_name
                    })
    return holidays


_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
}

_CME_URL = 'https://www.cmegroup.com/trading-hours.html'
_CME_REQUIRED_CATEGORIES = (
    ('new year',),
    ('martin luther king', 'mlk'),
    ('president',),
    ('good friday',),
    ('memorial',),
    ('juneteenth',),
    ('independence',),
    ('labor',),
    ('thanksgiving',),
    ('christmas',),
)


def _parse_month(token: str) -> int:
    month = _MONTHS.get(token.lower())
    if month is None:
        raise ValueError(f'Unknown month in CME date range: {token!r}')
    return month


def _parse_cme_date_range(range_text: str) -> tuple[date, date]:
    """Parse CME schedule windows such as '18 - 20 January 2026'."""
    text = range_text.replace('–', '-').replace('—', '-').strip()
    text = re.sub(r'\s+', ' ', text)

    full = re.match(
        r'^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$',
        text,
    )
    if full:
        d1, m1, y1, d2, m2, y2 = full.groups()
        start = date(int(y1), _parse_month(m1), int(d1))
        end = date(int(y2), _parse_month(m2), int(d2))
        if end < start:
            raise ValueError(f'CME date range end before start: {range_text!r}')
        return start, end

    shared = re.match(
        r'^(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$',
        text,
    )
    if shared:
        d1, d2, month_name, year = shared.groups()
        month = _parse_month(month_name)
        y = int(year)
        start = date(y, month, int(d1))
        end = date(y, month, int(d2))
        if end < start:
            raise ValueError(f'CME date range end before start: {range_text!r}')
        return start, end

    raise ValueError(f'Unrecognized CME date range: {range_text!r}')


def _dates_in_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _select_canonical_holiday_date(holiday_name: str, start: date, end: date) -> date:
    """Pick the actual holiday day from a CME multi-day trading-hours window."""
    days = list(_dates_in_range(start, end))
    if not days:
        raise ValueError(f'Empty CME date range for {holiday_name!r}')

    name = holiday_name.lower()

    def weekday_in_range(weekday: int) -> date:
        matches = [d for d in days if d.weekday() == weekday]
        if not matches:
            raise ValueError(
                f'No weekday={weekday} in CME range {start}–{end} for {holiday_name!r}'
            )
        return matches[0]

    if any(k in name for k in (
        'martin luther king', 'presidents', "president's", 'memorial', 'labor',
    )):
        return weekday_in_range(0)  # Monday

    if 'thanksgiving' in name:
        return weekday_in_range(3)  # Thursday

    if 'good friday' in name or 'juneteenth' in name:
        return weekday_in_range(4)  # Friday

    if 'christmas' in name:
        matches = [d for d in days if d.month == 12 and d.day == 25]
        if not matches:
            raise ValueError(f'No December 25 in CME range for {holiday_name!r}')
        return matches[0]

    if 'independence' in name:
        jul4 = [d for d in days if d.month == 7 and d.day == 4]
        if jul4 and jul4[0].weekday() < 5:
            return jul4[0]
        fridays = [d for d in days if d.weekday() == 4]
        mondays = [d for d in days if d.weekday() == 0]
        if fridays:
            return fridays[0]
        if mondays:
            return mondays[0]
        raise ValueError(
            f'No Independence Day / observed weekday in CME range for {holiday_name!r}'
        )

    if 'new year' in name:
        matches = [d for d in days if d.month == 1 and d.day == 1]
        if not matches:
            raise ValueError(f'No January 1 in CME range for {holiday_name!r}')
        return matches[0]

    raise ValueError(f'No date-selection rule for CME holiday name: {holiday_name!r}')


def _normalize_cme_holiday_name(raw_name: str, holiday_date: date) -> str:
    name = raw_name.lower()
    if 'new year' in name:
        return "New Year's Day"
    if 'martin luther king' in name:
        return 'MLK Jr. Day'
    if 'president' in name:
        return 'Presidents Day'
    if 'good friday' in name:
        return 'Good Friday'
    if 'memorial' in name:
        return 'Memorial Day'
    if 'juneteenth' in name:
        return 'Juneteenth'
    if 'independence' in name:
        if holiday_date.month == 7 and holiday_date.day == 4:
            return 'Independence Day'
        return 'Independence Day (observed)'
    if 'labor' in name:
        return 'Labor Day'
    if 'thanksgiving' in name:
        return 'Thanksgiving Day'
    if 'christmas' in name:
        return 'Christmas Day'
    return raw_name.strip()


def _format_holiday_date(d: date) -> str:
    return f'{d.strftime("%B")} {d.day}, {d.year}'


def _validate_cme_holidays(holidays: list[dict]) -> None:
    if not 9 <= len(holidays) <= 11:
        raise RuntimeError(
            f'CME result count looks wrong: expected ~10 records, got {len(holidays)}'
        )

    for record in holidays:
        human = record.get('date', '')
        try:
            record_date = pd.to_datetime(human, format='mixed').date()
        except Exception as exc:
            raise RuntimeError(f'Invalid CME date value: {human!r}') from exc
        if record_date.year != YEAR:
            raise RuntimeError(
                f'CME date {human!r} is not in target year {YEAR}'
            )

    names = ' '.join(h['holiday'].lower() for h in holidays)
    missing = []
    for keywords in _CME_REQUIRED_CATEGORIES:
        if not any(k in names for k in keywords):
            missing.append(keywords[0])
    if missing:
        raise RuntimeError(
            f'CME result missing expected holiday categories: {missing}'
        )


def scrape_cme():
    """Scrape the live CME Globex trading schedule via Playwright + Chromium."""
    print('Scraping CME (Playwright)...')
    target_heading = f'{YEAR} CME Globex Trading Schedule'
    holidays = []

    with sync_playwright() as p:
        # CME rejects Playwright's default/old headless with ERR_HTTP2_PROTOCOL_ERROR.
        # Chromium's newer headless mode loads the page successfully (HTTP 200).
        browser = p.chromium.launch(headless=False, args=['--headless=new'])
        try:
            context = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1280, 'height': 720},
            )
            page = context.new_page()
            response = page.goto(
                _CME_URL, wait_until='domcontentloaded', timeout=60_000
            )
            status = response.status if response else None
            if status != 200:
                raise RuntimeError(
                    f'CME page returned HTTP {status} (expected 200) for {_CME_URL}'
                )

            try:
                page.wait_for_load_state('networkidle', timeout=30_000)
            except Exception:
                pass

            try:
                accept = page.get_by_role('button', name='Accept All Cookies')
                accept.wait_for(state='visible', timeout=8_000)
                accept.click()
            except Exception:
                pass  # Banner absent or differently labeled — non-fatal

            heading = page.locator(f"h2:has-text('{target_heading}')").first
            if heading.count() == 0:
                raise RuntimeError(f'CME heading not found: {target_heading!r}')

            heading.scroll_into_view_if_needed()
            table = heading.locator('xpath=following::table[1]')
            if table.count() == 0:
                raise RuntimeError(
                    f'No table found after CME heading {target_heading!r}'
                )

            rows = table.locator('tr')
            row_count = rows.count()
            if row_count < 2:
                raise RuntimeError('CME schedule table has no data rows')

            for i in range(row_count):
                row = rows.nth(i)
                cells = row.locator('th, td')
                cell_count = cells.count()
                if cell_count < 2:
                    continue

                holiday_name = cells.nth(0).inner_text().strip()
                range_text = cells.nth(1).inner_text().strip()

                # Skip header row
                if 'holiday' in holiday_name.lower() and 'date' in range_text.lower():
                    continue
                if not holiday_name or not range_text:
                    continue

                start, end = _parse_cme_date_range(range_text)
                holiday_date = _select_canonical_holiday_date(
                    holiday_name, start, end
                )
                if holiday_date.year != YEAR:
                    continue

                holidays.append({
                    'exchange': 'CME',
                    'date': _format_holiday_date(holiday_date),
                    'holiday': _normalize_cme_holiday_name(
                        holiday_name, holiday_date
                    ),
                })
        finally:
            browser.close()

    # Deduplicate while preserving order (e.g. if page structure repeats)
    seen = set()
    unique = []
    for record in holidays:
        key = (record['date'], record['holiday'])
        if key not in seen:
            seen.add(key)
            unique.append(record)
    holidays = unique

    _validate_cme_holidays(holidays)
    return holidays


def scrape_opra():
    """
    OPRA holiday schedule.

    OPRA's official website is accessible, but its current document
    library does not provide a 2026 Holiday Schedule. Therefore,
    the verified 2026 schedule is maintained as a static fallback.
    """

    holidays = [
        {'exchange': 'OPRA', 'date': f'January 1, {YEAR}', 'holiday': "New Year's Day"},
        {'exchange': 'OPRA', 'date': f'January 19, {YEAR}', 'holiday': 'MLK Jr. Day'},
        {'exchange': 'OPRA', 'date': f'February 16, {YEAR}', 'holiday': 'Presidents Day'},
        {'exchange': 'OPRA', 'date': f'April 3, {YEAR}', 'holiday': 'Good Friday'},
        {'exchange': 'OPRA', 'date': f'May 25, {YEAR}', 'holiday': 'Memorial Day'},
        {'exchange': 'OPRA', 'date': f'June 19, {YEAR}', 'holiday': 'Juneteenth'},
        {'exchange': 'OPRA', 'date': f'July 3, {YEAR}', 'holiday': 'Independence Day (observed)'},
        {'exchange': 'OPRA', 'date': f'September 7, {YEAR}', 'holiday': 'Labor Day'},
        {'exchange': 'OPRA', 'date': f'November 26, {YEAR}', 'holiday': 'Thanksgiving Day'},
        {'exchange': 'OPRA', 'date': f'December 25, {YEAR}', 'holiday': 'Christmas Day'},
    ]

    return holidays
def upload_csv_to_drive(drive_service, csv_path):
    media = MediaFileUpload(csv_path, mimetype='text/csv', resumable=False)
    drive_service.files().update(
        fileId=CSV_FILE_ID,
        media_body=media
    ).execute()
    print(f"CSV updated in Google Drive: https://drive.google.com/file/d/{CSV_FILE_ID}/view")


def main():
    all_holidays = []

    scrapers = [scrape_nasdaq, scrape_nyse, scrape_cme, scrape_opra]
    for scraper in scrapers:
        try:
            data = scraper()
            all_holidays.extend(data)
            print(f"  → {len(data)} holidays found")
        except Exception as e:
            print(f"  → ERROR: {e}")

    if not all_holidays:
        print("No data scraped — check scrapers")
        return

    df = pd.DataFrame(all_holidays)
    df['date'] = pd.to_datetime(df['date'], errors='coerce', format='mixed')
    df = df.dropna(subset=['date'])
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    df = df.sort_values(['exchange', 'date']).reset_index(drop=True)

    print(f"\nTotal holidays collected: {len(df)}")
    print(df.to_string())

    csv_path = os.path.join(os.path.dirname(__file__), 'holidays.csv')
    df.to_csv(csv_path, index=False)
    print(f"\nCSV saved locally: {csv_path}")

    print("\nConnecting to Google...")
    client, drive_service = get_clients()

    # Update Google Sheet
    sh = client.open_by_key(SHEET_ID)
    ws = sh.sheet1
    ws.clear()
    ws.update([df.columns.tolist()] + df.values.tolist())
    print(f"Google Sheet updated: {sh.url}")

    # Upload CSV to Google Drive folder
    try:
        upload_csv_to_drive(drive_service, csv_path)
    except Exception as e:
        print(f"WARNING: Could not upload CSV to Drive: {e}")
        print(f"CSV is available locally at: {csv_path}")

    print("\nDone!")


if __name__ == '__main__':
    main()