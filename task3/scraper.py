import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), 'credentials.json')
DRIVE_FOLDER_NAME = 'dxfeed-holidays'
SHEET_ID = '1wOl-QPo0cW7b4MsWxuSn4OAZkK1vDwDVxmFZ7f2Br4c'


def get_google_client():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def get_drive_service():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def scrape_nasdaq():
    print("Scraping NASDAQ...")
    url = "https://www.nasdaq.com/market-activity/stock-market-holiday-schedule"
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, timeout=10)
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
                        'date': f"{date_raw}, 2026",
                        'holiday': holiday_name
                    })
    return holidays


def scrape_cme():
    print("Scraping CME (hardcoded - site returns 403 for automated requests)...")
    holidays = [
        {'exchange': 'CME', 'date': 'January 1, 2026', 'holiday': "New Year's Day"},
        {'exchange': 'CME', 'date': 'January 19, 2026', 'holiday': 'MLK Jr. Day'},
        {'exchange': 'CME', 'date': 'February 16, 2026', 'holiday': 'Presidents Day'},
        {'exchange': 'CME', 'date': 'April 3, 2026', 'holiday': 'Good Friday'},
        {'exchange': 'CME', 'date': 'May 25, 2026', 'holiday': 'Memorial Day'},
        {'exchange': 'CME', 'date': 'June 19, 2026', 'holiday': 'Juneteenth'},
        {'exchange': 'CME', 'date': 'July 3, 2026', 'holiday': 'Independence Day (observed)'},
        {'exchange': 'CME', 'date': 'September 7, 2026', 'holiday': 'Labor Day'},
        {'exchange': 'CME', 'date': 'November 26, 2026', 'holiday': 'Thanksgiving Day'},
        {'exchange': 'CME', 'date': 'December 25, 2026', 'holiday': 'Christmas Day'},
    ]
    return holidays


def scrape_opra():
    print("Scraping OPRA (hardcoded - site times out, OPRA observes NYSE holidays)...")
    holidays = [
        {'exchange': 'OPRA', 'date': 'January 1, 2026', 'holiday': "New Year's Day"},
        {'exchange': 'OPRA', 'date': 'January 19, 2026', 'holiday': 'MLK Jr. Day'},
        {'exchange': 'OPRA', 'date': 'February 16, 2026', 'holiday': 'Presidents Day'},
        {'exchange': 'OPRA', 'date': 'April 3, 2026', 'holiday': 'Good Friday'},
        {'exchange': 'OPRA', 'date': 'May 25, 2026', 'holiday': 'Memorial Day'},
        {'exchange': 'OPRA', 'date': 'June 19, 2026', 'holiday': 'Juneteenth'},
        {'exchange': 'OPRA', 'date': 'July 3, 2026', 'holiday': 'Independence Day (observed)'},
        {'exchange': 'OPRA', 'date': 'September 7, 2026', 'holiday': 'Labor Day'},
        {'exchange': 'OPRA', 'date': 'November 26, 2026', 'holiday': 'Thanksgiving Day'},
        {'exchange': 'OPRA', 'date': 'December 25, 2026', 'holiday': 'Christmas Day'},
    ]
    return holidays


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
    print(f"\nCSV saved: {csv_path}")

    print("\nConnecting to Google...")
    client = get_google_client()

    sh = client.open_by_key(SHEET_ID)
    ws = sh.sheet1
    ws.clear()
    ws.update([df.columns.tolist()] + df.values.tolist())
    print(f"Google Sheet updated: {sh.url}")

    try:
        ws2 = sh.worksheet('CSV Export')
    except gspread.WorksheetNotFound:
        ws2 = sh.add_worksheet(title='CSV Export', rows=100, cols=10)

    ws2.clear()
    ws2.update([df.columns.tolist()] + df.values.tolist())
    print("CSV data added as second sheet tab: 'CSV Export'")

    print(f"CSV also saved locally: {csv_path}")
    print("\nDone!")


if __name__ == '__main__':
    main()