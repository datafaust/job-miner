import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from openpyxl import Workbook, load_workbook

from job_tools import drive_export


class DriveExportTests(unittest.TestCase):
    @staticmethod
    def existing_workbook():
        workbook = Workbook()
        workbook.active.title = "Overview"
        workbook.active["A1"] = "Keep this value"
        workbook.create_sheet("Prospective jobs")["A1"] = "Old jobs"
        workbook.create_sheet("Notes")["B2"] = "Keep this too"
        data = BytesIO()
        workbook.save(data)
        return data.getvalue()

    def test_workbook_replaces_only_prospects_sheet_and_keeps_text_literal(self):
        rows = drive_export.prospect_rows([
            {"job_title": "=HYPERLINK(\"https://example.com\")", "company": "Acme", "url": "https://example.com/1"},
            {"job_title": "Analyst", "salary_range": None},
        ])
        data = drive_export.workbook_bytes(rows, self.existing_workbook())
        workbook = load_workbook(data)
        self.assertEqual(workbook.sheetnames, ["Overview", "Prospective jobs", "Notes"])
        self.assertEqual(workbook["Overview"]["A1"].value, "Keep this value")
        self.assertEqual(workbook["Notes"]["B2"].value, "Keep this too")
        sheet = workbook["Prospective jobs"]
        self.assertEqual(sheet.max_row, 3)
        self.assertEqual(sheet["A1"].value, "Job title")
        self.assertEqual(sheet["A2"].value, '=HYPERLINK("https://example.com")')
        self.assertEqual(sheet["A2"].data_type, "s")
        self.assertEqual(sheet["C3"].value, None)
        self.assertEqual(sheet["H2"].value, "https://example.com/1")
        refreshed = load_workbook(drive_export.workbook_bytes(
            drive_export.prospect_rows([]), data.getvalue()
        ))
        self.assertEqual(refreshed.sheetnames, ["Overview", "Prospective jobs", "Notes"])
        self.assertEqual(refreshed["Prospective jobs"].max_row, 1)
        self.assertEqual(refreshed["Overview"]["A1"].value, "Keep this value")

    def test_upload_updates_only_the_configured_excel_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "prospective_jobs.json"
            source.write_text(json.dumps([{"job_title": "Analyst"}]), encoding="utf-8")
            service = MagicMock()
            service.files.return_value.get.return_value.execute.return_value = {
                "id": "target", "name": "jobs.xlsx", "mimeType": drive_export.XLSX_MIME
            }
            service.files.return_value.get_media.return_value.execute.return_value = self.existing_workbook()
            service.files.return_value.update.return_value.execute.return_value = {
                "id": "target", "name": "jobs.xlsx"
            }
            with patch.object(drive_export, "drive_credentials", return_value=object()), \
                 patch.object(drive_export, "build", return_value=service):
                count, result = drive_export.upload_json(source, "target", Path("client.json"), Path("token.json"))
            self.assertEqual(count, 1)
            self.assertEqual(result["id"], "target")
            service.files.return_value.update.assert_called_once()
            kwargs = service.files.return_value.update.call_args.kwargs
            self.assertEqual(kwargs["fileId"], "target")
            self.assertEqual(kwargs["media_body"].mimetype(), drive_export.XLSX_MIME)
            uploaded = kwargs["media_body"]
            workbook = load_workbook(BytesIO(uploaded.getbytes(0, uploaded.size())))
            self.assertEqual(workbook["Overview"]["A1"].value, "Keep this value")
            self.assertEqual(workbook["Prospective jobs"]["A2"].value, "Analyst")
            service.files.return_value.get_media.assert_called_once_with(
                fileId="target", supportsAllDrives=True
            )

    def test_adds_prospects_sheet_when_missing(self):
        workbook = Workbook()
        workbook.active.title = "Overview"
        original = BytesIO()
        workbook.save(original)
        updated = load_workbook(drive_export.workbook_bytes(
            drive_export.prospect_rows([]), original.getvalue()
        ))
        self.assertEqual(updated.sheetnames, ["Overview", "Prospective jobs"])
        self.assertEqual(updated["Prospective jobs"]["A1"].value, "Job title")

    def test_rejects_unsupported_file_type_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "prospective_jobs.json"
            source.write_text("[]", encoding="utf-8")
            service = MagicMock()
            service.files.return_value.get.return_value.execute.return_value = {
                "mimeType": "application/pdf"
            }
            with patch.object(drive_export, "drive_credentials", return_value=object()), \
                 patch.object(drive_export, "build", return_value=service):
                with self.assertRaisesRegex(ValueError, "Google Sheet or an existing .xlsx"):
                    drive_export.upload_json(source, "target", Path("client.json"), Path("token.json"))
            service.files.return_value.update.assert_not_called()

    def test_native_google_sheet_updates_only_prospects_tab(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "prospective_jobs.json"
            source.write_text(json.dumps([{"job_title": "=not a formula"}]), encoding="utf-8")
            drive = MagicMock()
            drive.files.return_value.get.return_value.execute.return_value = {
                "id": "target", "name": "Jobs", "mimeType": drive_export.SHEETS_MIME
            }
            sheets = MagicMock()
            sheets.spreadsheets.return_value.get.return_value.execute.return_value = {
                "sheets": [
                    {"properties": {"sheetId": 11, "title": "Overview"}},
                    {"properties": {"sheetId": 22, "title": "Prospective jobs",
                                    "gridProperties": {"rowCount": 1000, "columnCount": 26}}},
                ]
            }
            with patch.object(drive_export, "drive_credentials", return_value=object()), \
                 patch.object(drive_export, "build", side_effect=[drive, sheets]):
                count, result = drive_export.upload_json(
                    source, "target", Path("client.json"), Path("token.json")
                )
            self.assertEqual(count, 1)
            self.assertEqual(result["id"], "target")
            self.assertEqual(result["webViewLink"],
                             "https://docs.google.com/spreadsheets/d/target/edit#gid=22")
            drive.files.return_value.get_media.assert_not_called()
            drive.files.return_value.update.assert_not_called()
            calls = sheets.spreadsheets.return_value.batchUpdate.call_args_list
            self.assertEqual(len(calls), 1)
            requests = calls[0].kwargs["body"]["requests"]
            self.assertEqual(requests[0]["repeatCell"]["range"]["sheetId"], 22)
            self.assertEqual(requests[1]["updateCells"]["rows"][1]["values"][0], {
                "userEnteredValue": {"stringValue": "=not a formula"}
            })

    def test_native_google_sheet_creates_tab_if_missing(self):
        sheets = MagicMock()
        sheets.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"sheetId": 11, "title": "Overview"}}]
        }
        sheets.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"addSheet": {"properties": {"sheetId": 33}}}]
        }
        with patch.object(drive_export, "build", return_value=sheets):
            drive_export.update_google_sheet(object(), "target", drive_export.prospect_rows([]))
        calls = sheets.spreadsheets.return_value.batchUpdate.call_args_list
        self.assertEqual(calls[0].kwargs["body"]["requests"][0]["addSheet"]["properties"]["title"],
                         "Prospective jobs")
        self.assertEqual(calls[1].kwargs["body"]["requests"][0]["repeatCell"]["range"]["sheetId"], 33)


if __name__ == "__main__":
    unittest.main()
