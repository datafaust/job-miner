"""Refresh the Prospective jobs worksheet in an Excel workbook on Drive."""

import argparse
import json
import os
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from openpyxl import load_workbook
from openpyxl.styles import Font

from job_tools.job_stats import source_counts


PROJECT_DIR = Path(__file__).resolve().parent.parent
SCOPES = ["https://www.googleapis.com/auth/drive"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
SHEET_NAME = "Prospective jobs"
COLUMNS = (
    ("job_title", "Job title"),
    ("company", "Company"),
    ("salary_range", "Salary range"),
    ("posted_at", "Posted at"),
    ("posted_text", "Posted text"),
    ("remote_status", "Remote status"),
    ("location", "Location"),
    ("url", "URL"),
    ("source", "Source"),
    ("source_saved_at", "Source saved at"),
    ("extracted_at", "Extracted at"),
    ("job_key", "Job key"),
)


def prospect_rows(prospects):
    if not isinstance(prospects, list) or any(not isinstance(row, dict) for row in prospects):
        raise ValueError("Prospective jobs JSON must be an array of objects")
    return [[label for _, label in COLUMNS]] + [
        ["" if prospect.get(key) is None else str(prospect[key]) for key, _ in COLUMNS]
        for prospect in prospects
    ]


def workbook_bytes(rows, existing_content):

    workbook = load_workbook(BytesIO(existing_content))
    old_sheet = next(
        (sheet for sheet in workbook if sheet.title.casefold() == SHEET_NAME.casefold()),
        None,
    )
    position = workbook.index(old_sheet) if old_sheet is not None else len(workbook.worksheets)
    if old_sheet is not None:
        workbook.remove(old_sheet)
    sheet = workbook.create_sheet(SHEET_NAME, position)
    sheet.append(rows[0])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows[1:]:
        sheet.append([None] * len(COLUMNS))
        for column, value in enumerate(row, start=1):
            if value:
                cell = sheet.cell(sheet.max_row, column, value)
                # Posting text is untrusted input; keep Excel formula-like text literal.
                cell.data_type = "s"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in {"A": 40, "B": 28, "C": 25, "D": 27, "E": 27,
                          "F": 16, "G": 35, "H": 65, "I": 18, "J": 27,
                          "K": 27, "L": 40}.items():
        sheet.column_dimensions[column].width = width
    data = BytesIO()
    workbook.save(data)
    data.seek(0)
    return data


def update_google_sheet(credentials, file_id, rows):
    """Refresh only the named tab in a native Google Sheets spreadsheet."""
    spreadsheets = build("sheets", "v4", credentials=credentials).spreadsheets()
    metadata = spreadsheets.get(
        spreadsheetId=file_id,
        fields="sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))",
    ).execute()
    existing = next(
        (sheet["properties"] for sheet in metadata.get("sheets", [])
         if sheet["properties"]["title"].casefold() == SHEET_NAME.casefold()),
        None,
    )
    if existing is None:
        response = spreadsheets.batchUpdate(
            spreadsheetId=file_id,
            body={"requests": [{"addSheet": {"properties": {
                "title": SHEET_NAME,
                "gridProperties": {
                    "rowCount": max(1000, len(rows)),
                    "columnCount": max(26, len(COLUMNS)),
                    "frozenRowCount": 1,
                },
            }}}]},
        ).execute()
        sheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]
        grid = {"rowCount": max(1000, len(rows)), "columnCount": max(26, len(COLUMNS))}
    else:
        sheet_id = existing["sheetId"]
        grid = existing.get("gridProperties", {})

    requests = []
    if grid.get("rowCount", 0) < len(rows) or grid.get("columnCount", 0) < len(COLUMNS):
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {
                "rowCount": max(grid.get("rowCount", 0), len(rows)),
                "columnCount": max(grid.get("columnCount", 0), len(COLUMNS)),
            }},
            "fields": "gridProperties.rowCount,gridProperties.columnCount",
        }})
    requests.extend([
        {"repeatCell": {
            "range": {"sheetId": sheet_id},
            "cell": {},
            "fields": "userEnteredValue",
        }},
        {"updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
            "rows": [{"values": [{"userEnteredValue": {"stringValue": value}}
                                for value in row]} for row in rows],
            "fields": "userEnteredValue",
        }},
    ])
    spreadsheets.batchUpdate(spreadsheetId=file_id, body={"requests": requests}).execute()
    return sheet_id


def drive_credentials(client_secrets_file, token_file):
    credentials = None
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            credentials = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets_file), SCOPES
            ).run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")
        token_file.chmod(0o600)
    return credentials


def upload_json(input_file, file_id, client_secrets_file, token_file):
    prospects = json.loads(input_file.read_text(encoding="utf-8"))
    rows = prospect_rows(prospects)
    credentials = drive_credentials(client_secrets_file, token_file)
    service = build("drive", "v3", credentials=credentials)
    target = service.files().get(
        fileId=file_id, fields="id,name,mimeType,webViewLink", supportsAllDrives=True
    ).execute()
    if target["mimeType"] == SHEETS_MIME:
        sheet_id = update_google_sheet(credentials, file_id, rows)
        target["webViewLink"] = f"https://docs.google.com/spreadsheets/d/{file_id}/edit#gid={sheet_id}"
        return len(prospects), target
    if target["mimeType"] != XLSX_MIME:
        raise ValueError(f"Drive file {file_id} must be a Google Sheet or an existing .xlsx file")
    existing_content = service.files().get_media(
        fileId=file_id, supportsAllDrives=True
    ).execute()
    workbook = workbook_bytes(rows, existing_content)
    updated = service.files().update(
        fileId=file_id,
        media_body=MediaIoBaseUpload(workbook, mimetype=XLSX_MIME, resumable=False),
        fields="id,name,webViewLink",
        supportsAllDrives=True,
    ).execute()
    return len(prospects), updated


def main():
    load_dotenv(PROJECT_DIR / ".env")
    parser = argparse.ArgumentParser(description="Refresh Prospective jobs in a Google Sheet or Drive Excel file.")
    parser.add_argument("--input", type=Path, default=Path("prospective_jobs.json"))
    args = parser.parse_args()
    file_id = os.getenv("GOOGLE_DRIVE_FILE_ID", "").strip()
    client_secrets = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip()
    if not file_id or not client_secrets:
        parser.error("Set GOOGLE_DRIVE_FILE_ID and GOOGLE_OAUTH_CLIENT_SECRETS_FILE in .env")
    client_secrets_file = Path(client_secrets).expanduser()
    if not client_secrets_file.is_file():
        parser.error(f"OAuth client JSON not found: {client_secrets_file}")
    token_file = Path(os.getenv("GOOGLE_OAUTH_TOKEN_FILE", ".google_drive_token.json")).expanduser()
    count, updated = upload_json(args.input, file_id, client_secrets_file, token_file)
    print(f"Updated Prospective jobs with {count} jobs in {updated['name']} ({updated.get('webViewLink', file_id)}).")
    exported = json.loads(args.input.read_text(encoding="utf-8"))
    print(f"Sheet rows by source: {source_counts(row.get('source', 'Other') for row in exported)}.")


if __name__ == "__main__":
    main()
