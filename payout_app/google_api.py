"""
google_api.py - Signing in to Google and the Sheets calls the app needs
=======================================================================

WHAT THIS MODULE DOES
---------------------
Everything that talks to Google is kept here, so the rest of the payout
app works with plain rows and can be tested without the internet.

    sign_in()                     the user's Google sign-in (asked once per
                                  PC, then remembered)
    SheetsClient(credentials)
        .create(title, tabs, layout)   make a new Google Sheet, fill its
                                       tabs and format them
        .read_tabs(sheet_id)           every tab's rows, as typed
        .title(sheet_id)               the sheet's name

SIGNING IN
----------
Google needs two files:
    1. The app's key file - "client_secret_....json", downloaded once from
       the Google Cloud project "Drive N Style Tools" (owner:
       automation.drivenstyle@gmail.com). It identifies the APP, not a
       person. It is looked for in this order:
           * the path in the environment variable DNS_GOOGLE_CLIENT_SECRET
           * the app's data folder (%LOCALAPPDATA%\\Drive N Style Reports)
           * the project's "data" folder (development)
       It must never be committed to Git (/data/ is ignored).
    2. The person's sign-in - created the first time: the browser opens,
       the person chooses their Google account and allows access. The
       result is saved as "google_token.json" in the data folder and
       renewed silently afterwards. Deleting that file signs the PC out.
While the Google project is in "Testing", only the accounts listed there as
test users can sign in, and Google asks for the sign-in again every 7 days.

WHAT THE APP MAY DO IN GOOGLE (scopes)
--------------------------------------
    spreadsheets   read and write Google Sheets the signed-in person can
                   open (the masters sheet, later the payout register)
    drive.file     only files this app itself created or was given
                   (later: the payment proofs it uploads) - never the
                   person's other Drive files

HOW CELLS ARE READ
------------------
`read_tabs` asks for the values as stored, not as displayed: a number
comes as a number whatever its format, and a real date comes as a date
serial number (masters_sheet.parse_sheet_date turns it into a date). A date
typed as text comes as that text. This keeps the reading independent of
the sheet's language and number formats.

The Google libraries are imported only when needed, so the rest of the app
(and the tests) run without them installed.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.data.paths import data_dir

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = "google_token.json"
SECRET_PATTERN = "client_secret*.json"
# Header row colours: the tool's blue (app/theme.py Colors.BLUE, #1F5FBF)
# with white text.
HEADER_FILL = {"red": 0.122, "green": 0.373, "blue": 0.749}
WHITE = {"red": 1, "green": 1, "blue": 1}


class GoogleError(Exception):
    """Sign-in or a Google call failed; the message is for the user."""


def _libraries():
    """Import Google's libraries, with a plain message if they are missing."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleError(
            "Google's libraries are not installed. Run:  "
            "pip install -r requirements.txt") from exc
    return Request, Credentials, InstalledAppFlow, build


def find_client_secret() -> Path:
    """The app's key file (see SIGNING IN above)."""
    given = os.environ.get("DNS_GOOGLE_CLIENT_SECRET", "").strip()
    if given:
        if Path(given).is_file():
            return Path(given)
        raise GoogleError(f"DNS_GOOGLE_CLIENT_SECRET points to “{given}”, "
                          "which is not a file.")
    project_data = Path(__file__).resolve().parent.parent / "data"
    for folder in (data_dir(), project_data):
        hits = sorted(folder.glob(SECRET_PATTERN)) if folder.is_dir() else []
        if hits:
            return hits[0]
    raise GoogleError(
        "The app's Google key file (client_secret_....json) was not found. "
        f"Put it in “{data_dir()}”.")


def token_path() -> Path:
    return data_dir() / TOKEN_FILE


def sign_in(interactive: bool = True):
    """
    The signed-in person's Google credentials.
    Uses the saved sign-in when there is one (renewing it if it has run
    out); otherwise opens the browser to sign in - unless `interactive` is
    False, when a GoogleError is raised instead.
    """
    Request, Credentials, InstalledAppFlow, _ = _libraries()
    creds = None
    if token_path().is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)
        except ValueError:
            creds = None                               # damaged file: sign in again
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path().write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:
            creds = None      # sign-in withdrawn or run out (7 days in Testing)
    if not interactive:
        raise GoogleError("This PC is not signed in to Google.")
    flow = InstalledAppFlow.from_client_secrets_file(str(find_client_secret()), SCOPES)
    try:
        creds = flow.run_local_server(port=0, prompt="consent")
    except Exception as exc:
        raise GoogleError(f"Google sign-in did not finish ({exc}).") from exc
    token_path().write_text(creds.to_json(), encoding="utf-8")
    return creds


# ---------------------------------------------------------------------------
# Formatting requests for a new sheet (plain dicts - tested without Google)
# ---------------------------------------------------------------------------
def column_layout(kind: str, choices: tuple = (), strict: bool = True) -> dict:
    """How one column is formatted: kind = text / money / date / yesno / choice."""
    return {"kind": kind, "choices": tuple(choices), "strict": strict}


def format_requests(sheet_id: int, columns: list[dict], header_count: int) -> list[dict]:
    """
    The formatting of one tab, as Google "batchUpdate" requests:
    blue heading row, drop-downs for Yes/No and choice columns, date and
    amount formats, and column widths fitted to the contents.
    """
    def col(i: int, from_row: int = 1) -> dict:
        return {"sheetId": sheet_id, "startRowIndex": from_row,
                "startColumnIndex": i, "endColumnIndex": i + 1}

    requests: list[dict] = [{"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": header_count},
        "cell": {"userEnteredFormat": {
            "backgroundColor": HEADER_FILL,
            "textFormat": {"bold": True, "foregroundColor": WHITE}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}}]
    for i, layout in enumerate(columns):
        kind = layout["kind"]
        if kind in ("yesno", "choice"):
            values = ("Yes", "No") if kind == "yesno" else layout["choices"]
            requests.append({"setDataValidation": {
                "range": col(i),
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                             {"userEnteredValue": v} for v in values]},
                         "strict": bool(layout.get("strict", True)),
                         "showCustomUi": True}}})
        elif kind in ("money", "date"):
            number_format = {"type": "NUMBER", "pattern": "#,##0.00"} if kind == "money" \
                else {"type": "DATE", "pattern": "dd-mm-yyyy"}
            requests.append({"repeatCell": {
                "range": col(i),
                "cell": {"userEnteredFormat": {"numberFormat": number_format}},
                "fields": "userEnteredFormat.numberFormat"}})
        elif kind == "text":
            # Plain text, so a contact number or code keeps its digits as typed.
            requests.append({"repeatCell": {
                "range": col(i),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                "fields": "userEnteredFormat.numberFormat"}})
    requests.append({"autoResizeDimensions": {"dimensions": {
        "sheetId": sheet_id, "dimension": "COLUMNS",
        "startIndex": 0, "endIndex": header_count}}})
    return requests


def _quoted(tab: str) -> str:
    """A tab name as a range: 'Sales executives' (quotes doubled inside)."""
    return "'" + tab.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# The Sheets calls
# ---------------------------------------------------------------------------
class SheetsClient:
    """The few Google Sheets operations the payout app uses."""

    def __init__(self, credentials=None, service=None):
        """`service` is only given by the tests (a stand-in for Google)."""
        if service is None:
            _, _, _, build = _libraries()
            service = build("sheets", "v4", credentials=credentials,
                            cache_discovery=False)
        self.sheets = service.spreadsheets()

    def _run(self, request, doing: str):
        try:
            return request.execute()
        except Exception as exc:
            raise GoogleError(f"Google could not {doing}: {_reason(exc)}") from exc

    def create(self, title: str, tabs: dict[str, list[list]],
               layout: dict[str, list[dict]] | None = None) -> tuple[str, str]:
        """
        Make a new Google Sheet in the signed-in person's Drive.
        tabs    tab name -> rows (row 1 = headings)
        layout  tab name -> one column_layout per column (optional)
        Returns (sheet id, link).
        """
        layout = layout or {}
        body = {
            # en_GB: a date typed as 05/10/2026 is read day first (5 October).
            "properties": {"title": title, "locale": "en_GB",
                           "timeZone": "Asia/Kolkata"},
            "sheets": [{"properties": {
                "title": name,
                "gridProperties": {"frozenRowCount": 1,
                                   "rowCount": max(len(rows) + 500, 1000),
                                   "columnCount": max(len(rows[0]) if rows else 1, 1)}}}
                for name, rows in tabs.items()],
        }
        made = self._run(self.sheets.create(
            body=body, fields="spreadsheetId,spreadsheetUrl,sheets.properties"),
            "create the sheet")
        sheet_id = made["spreadsheetId"]
        ids = {s["properties"]["title"]: s["properties"]["sheetId"]
               for s in made.get("sheets", [])}
        self._run(self.sheets.values().batchUpdate(
            spreadsheetId=sheet_id,
            body={"valueInputOption": "RAW",
                  "data": [{"range": f"{_quoted(name)}!A1", "values": rows}
                           for name, rows in tabs.items() if rows]}),
            "fill the sheet")
        requests: list[dict] = []
        for name, rows in tabs.items():
            if name in ids and rows:
                requests += format_requests(ids[name], layout.get(name, []), len(rows[0]))
        if requests:
            self._run(self.sheets.batchUpdate(
                spreadsheetId=sheet_id, body={"requests": requests}),
                "format the sheet")
        return sheet_id, made.get(
            "spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit")

    def tab_names(self, sheet_id: str) -> list[str]:
        meta = self._run(self.sheets.get(
            spreadsheetId=sheet_id, fields="sheets.properties.title"), "open the sheet")
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    def title(self, sheet_id: str) -> str:
        meta = self._run(self.sheets.get(
            spreadsheetId=sheet_id, fields="properties.title"), "open the sheet")
        return meta.get("properties", {}).get("title", "")

    def read_tabs(self, sheet_id: str) -> dict[str, list[list]]:
        """Every tab's rows (see HOW CELLS ARE READ above)."""
        names = self.tab_names(sheet_id)
        if not names:
            return {}
        got = self._run(self.sheets.values().batchGet(
            spreadsheetId=sheet_id, ranges=[_quoted(n) for n in names],
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="SERIAL_NUMBER"), "read the sheet")
        ranges = got.get("valueRanges", [])
        return {name: (ranges[i].get("values", []) if i < len(ranges) else [])
                for i, name in enumerate(names)}


def _reason(exc: Exception) -> str:
    """A short, plain reason from a Google error."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in (403, "403"):
        return "this Google account is not allowed to open it (ask for it to be shared)."
    if status in (404, "404"):
        return "the sheet was not found (check the link)."
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:200]
