import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv
import os

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


def scrape_cme():
    print("Scraping CME (hardcoded - site returns 403 for automated requests)...")
    holidays = [
        {'exchange': 'CME', 'date': f'January 1, {YEAR}', 'holiday': "New Year's Day"},
        {'exchange': 'CME', 'date': f'January 19, {YEAR}', 'holiday': 'MLK Jr. Day'},
        {'exchange': 'CME', 'date': f'February 16, {YEAR}', 'holiday': 'Presidents Day'},
        {'exchange': 'CME', 'date': f'April 3, {YEAR}', 'holiday': 'Good Friday'},
        {'exchange': 'CME', 'date': f'May 25, {YEAR}', 'holiday': 'Memorial Day'},
        {'exchange': 'CME', 'date': f'June 19, {YEAR}', 'holiday': 'Juneteenth'},
        {'exchange': 'CME', 'date': f'July 3, {YEAR}', 'holiday': 'Independence Day (observed)'},
        {'exchange': 'CME', 'date': f'September 7, {YEAR}', 'holiday': 'Labor Day'},
        {'exchange': 'CME', 'date': f'November 26, {YEAR}', 'holiday': 'Thanksgiving Day'},
        {'exchange': 'CME', 'date': f'December 25, {YEAR}', 'holiday': 'Christmas Day'},
    ]
    return holidays


def scrape_opra():
    print("Scraping OPRA (hardcoded - site times out, OPRA observes NYSE holidays)...")
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