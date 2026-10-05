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
        .append_rows(sheet_id, tab, rows)      add rows below the last one
        .update_rows(sheet_id, updates)        overwrite given rows from column A
        .write_formulas(sheet_id, tab, rows)   cells Google should work out
        .update_ranges(sheet_id, updates)      overwrite cells from a given cell
        .add_tab(sheet_id, title, rows)        add a tab to an existing sheet
        .clear_rows(sheet_id, tabs)            empty tabs below their headings
    DriveClient(credentials)
        .create_folder(name)                   a folder in the person's Drive
        .folder_name(folder_id)                check a folder can be opened
        .upload(path, name, folder_id)         put a file in a folder -> link
        .copy(file_id, name)                   a copy of a file (backup) -> link
        .owned_by_me(file_id)                  is the signed-in person the owner?
        .list_named(names)                     the person's own files with these names
        .trash(file_id)                        move a file to Drive's trash
    who(credentials)              name of the signed-in person, for the log

SIGNING IN
----------
Google needs two files:
    1. The app's key file - "client_secret_....json", downloaded once from
       the Google Cloud project "Drive N Style Tools" (owner:
       automation.drivenstyle@gmail.com). It identifies the APP, not a
       person. It is looked for in this order:
           * the path in the environment variable DNS_GOOGLE_CLIENT_SECRET
           * the app's data folder (%LOCALAPPDATA%\\Drive N Style Reports)
           * inside the installed app (v0.18.0: the build puts it there, so
             a staff PC needs nothing copied by hand)
           * the project's "data" folder (development)
       It must never be committed to Git (/data/ is ignored).
    2. The person's sign-in - created the first time: the browser opens,
       the person chooses their Google account and allows access. The
       result is saved as "google_token.json" in the data folder and
       renewed silently afterwards. Deleting that file signs the PC out.
While the Google project is in "Testing", only the accounts listed there as
test users can sign in, and Google asks for the sign-in again every 7 days.

The sign-in page is opened in MICROSOFT EDGE when it is installed (Brinda,
05-10-2026: Chrome holds people's other Google accounts, so the wrong
account was easily picked there); otherwise in the default browser.

WHAT THE APP MAY DO IN GOOGLE (scopes)
--------------------------------------
    spreadsheets   read and write Google Sheets the signed-in person can
                   open (the masters sheet, the payout register)
    drive          the person's Google Drive. Needed for the payment
                   proofs (v0.16.0, Brinda's choice "A"): they are kept in
                   ONE shared folder owned by the automation account, and
                   Google's narrower "only this app's own files" permission
                   cannot write into a folder someone else created. The app
                   only ever touches that one folder.
A sign-in saved before the permissions changed is noticed (its list of
permissions is shorter) and asked for again, once.

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
          "https://www.googleapis.com/auth/drive"]
SIGN_IN_WAIT_SECONDS = 300      # give up waiting for the browser after 5 minutes
EDGE_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
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
    from payout_app.settings import bundle_dir
    project_data = Path(__file__).resolve().parent.parent / "data"
    for folder in (data_dir(), bundle_dir(), project_data):
        hits = sorted(folder.glob(SECRET_PATTERN)) if folder and folder.is_dir() else []
        if hits:
            return hits[0]
    raise GoogleError(
        "The app's Google key file (client_secret_....json) was not found. "
        f"Put it in “{data_dir()}”.")


def token_path() -> Path:
    return data_dir() / TOKEN_FILE


def _saved_scopes() -> set[str]:
    """The permissions the saved sign-in was given (empty if none saved)."""
    import json
    try:
        data = json.loads(token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    scopes = data.get("scopes") or []
    return set(scopes.split() if isinstance(scopes, str) else scopes)


def is_signed_in() -> bool:
    """True when a sign-in with all the needed permissions is saved on this PC."""
    return token_path().is_file() and set(SCOPES) <= _saved_scopes()


def sign_out() -> None:
    """Forget the saved sign-in on this PC (the next use asks again)."""
    try:
        token_path().unlink()
    except OSError:
        pass


def _prefer_edge() -> None:
    """Make Edge the browser Python opens, when Edge is installed (Windows)."""
    import webbrowser
    for path in EDGE_PATHS:
        if Path(path).is_file():
            try:
                webbrowser.register("edge", None, webbrowser.BackgroundBrowser(path),
                                    preferred=True)
            except Exception:
                pass
            return


def sign_in(interactive: bool = True):
    """
    The signed-in person's Google credentials.
    Uses the saved sign-in when there is one (renewing it if it has run
    out); otherwise opens the browser to sign in - unless `interactive` is
    False, when a GoogleError is raised instead.
    """
    Request, Credentials, InstalledAppFlow, _ = _libraries()
    creds = None
    if token_path().is_file() and set(SCOPES) <= _saved_scopes():
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
    _prefer_edge()
    try:
        creds = flow.run_local_server(port=0, prompt="consent",
                                      timeout_seconds=SIGN_IN_WAIT_SECONDS)
    except KeyboardInterrupt:
        # Ctrl+C in the command window (often pressed to copy the link)
        raise GoogleError(
            "The sign-in was stopped (Ctrl+C). Run the command again and leave "
            "the window alone until the browser says the sign-in has completed. "
            "To copy the link, select it and right-click.") from None
    except Exception as exc:
        raise GoogleError(
            "Google sign-in did not finish. Please try again and complete it in "
            f"the browser window that opens. ({exc.__class__.__name__})") from exc
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
        # "warn": Google asks "are you sure?" before the cell is edited by
        # hand (it cannot refuse - see register.py). "hidden": column hidden.
        if layout.get("warn"):
            requests.append({"addProtectedRange": {"protectedRange": {
                "range": {"sheetId": sheet_id, "startColumnIndex": i,
                          "endColumnIndex": i + 1},
                "description": "Calculated by the payout app - do not edit",
                "warningOnly": True}}})
        if layout.get("hidden"):
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": i, "endIndex": i + 1},
                "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
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


    def append_rows(self, sheet_id: str, tab: str, rows: list[list]) -> None:
        """Add rows below the last filled row of a tab."""
        if not rows:
            return
        self._run(self.sheets.values().append(
            spreadsheetId=sheet_id, range=f"{_quoted(tab)}!A1",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": rows}), f"add rows to {tab}")

    def update_rows(self, sheet_id: str, updates: list[tuple[str, int, list]]) -> None:
        """Overwrite rows: (tab, sheet row number, cells from column A)."""
        if not updates:
            return
        self._run(self.sheets.values().batchUpdate(
            spreadsheetId=sheet_id,
            body={"valueInputOption": "RAW",
                  "data": [{"range": f"{_quoted(tab)}!A{row}", "values": [cells]}
                           for tab, row, cells in updates]}), "update the sheet")

    def update_ranges(self, sheet_id: str, updates: list[tuple[str, str, list[list]]]
                      ) -> None:
        """Overwrite cells: (tab, top-left cell such as "K7", rows of cells)."""
        if not updates:
            return
        self._run(self.sheets.values().batchUpdate(
            spreadsheetId=sheet_id,
            body={"valueInputOption": "RAW",
                  "data": [{"range": f"{_quoted(tab)}!{cell}", "values": rows}
                           for tab, cell, rows in updates]}), "update the sheet")

    def clear_rows(self, sheet_id: str, tabs: list[str]) -> None:
        """Empty every row below the headings of these tabs (formats stay)."""
        if not tabs:
            return
        self._run(self.sheets.values().batchClear(
            spreadsheetId=sheet_id,
            body={"ranges": [f"{_quoted(tab)}!A2:ZZ" for tab in tabs]}),
            "clear the sheet")

    def add_tab(self, sheet_id: str, title: str, rows: list[list]) -> None:
        """Add a tab (for a register made before the tab existed) and fill it."""
        self._run(self.sheets.batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]}),
            f"add the tab {title}")
        self.update_ranges(sheet_id, [(title, "A1", rows)])

    def write_formulas(self, sheet_id: str, tab: str, rows: list[list]) -> None:
        """Write cells that Google should interpret (formulas), from A1."""
        self._run(self.sheets.values().update(
            spreadsheetId=sheet_id, range=f"{_quoted(tab)}!A1",
            valueInputOption="USER_ENTERED", body={"values": rows}),
            f"fill {tab}")


class DriveClient:
    """The Google Drive operations the payout app uses (payment proofs)."""

    FOLDER_TYPE = "application/vnd.google-apps.folder"

    def __init__(self, credentials=None, service=None):
        """`service` is only given by the tests (a stand-in for Google)."""
        if service is None:
            _, _, _, build = _libraries()
            service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.files = service.files()

    def _run(self, request, doing: str):
        try:
            return request.execute()
        except Exception as exc:
            raise GoogleError(f"Google could not {doing}: {_reason(exc)}") from exc

    def create_folder(self, name: str) -> tuple[str, str]:
        """Make a folder in the signed-in person's Drive. Returns (id, link)."""
        made = self._run(self.files.create(
            body={"name": name, "mimeType": self.FOLDER_TYPE},
            fields="id,webViewLink"), "create the folder")
        return made["id"], made.get(
            "webViewLink", f"https://drive.google.com/drive/folders/{made['id']}")

    def folder_name(self, folder_id: str) -> str:
        """The folder's name - fails with a plain message if it cannot be opened."""
        got = self._run(self.files.get(fileId=folder_id, fields="id,name,mimeType",
                                       supportsAllDrives=True), "open the proofs folder")
        if got.get("mimeType") != self.FOLDER_TYPE:
            raise GoogleError("The proofs folder link does not point to a folder.")
        return got.get("name", "")

    def upload(self, path: str | Path, name: str, folder_id: str) -> str:
        """Upload a file into a folder under `name`. Returns its link."""
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise GoogleError("Google's libraries are not installed. Run:  "
                              "pip install -r requirements.txt") from exc
        media = MediaFileUpload(str(path), resumable=False)
        made = self._run(self.files.create(
            body={"name": name, "parents": [folder_id]}, media_body=media,
            fields="id,webViewLink", supportsAllDrives=True), "upload the proof")
        return made.get("webViewLink",
                        f"https://drive.google.com/file/d/{made['id']}/view")


    def copy(self, file_id: str, name: str) -> str:
        """Make a copy of a file in the signed-in person's Drive. Returns its link."""
        made = self._run(self.files.copy(fileId=file_id, body={"name": name},
                                         fields="id,webViewLink", supportsAllDrives=True),
                         "make the backup copy")
        return made.get("webViewLink",
                        f"https://docs.google.com/spreadsheets/d/{made['id']}/edit")

    def owned_by_me(self, file_id: str) -> bool:
        got = self._run(self.files.get(fileId=file_id, fields="ownedByMe",
                                       supportsAllDrives=True), "open the file")
        return bool(got.get("ownedByMe"))

    def list_named(self, names: list[str]) -> list[dict]:
        """
        The signed-in person's OWN files (not in the trash) whose name is
        exactly one of `names`, oldest first: id, name, mimeType,
        createdTime, webViewLink.
        """
        wanted = " or ".join("name = '{}'".format(n.replace("\\", "\\\\").replace("'", "\\'"))
                             for n in names)
        query = f"trashed = false and 'me' in owners and ({wanted})"
        found, token = [], None
        while True:
            page = self._run(self.files.list(
                q=query, pageSize=200, pageToken=token, orderBy="createdTime",
                fields="nextPageToken, files(id,name,mimeType,createdTime,webViewLink)"),
                "list the files")
            found += page.get("files", [])
            token = page.get("nextPageToken")
            if not token:
                return found

    def trash(self, file_id: str) -> None:
        """Move a file to Drive's trash (Google keeps it there for 30 days)."""
        self._run(self.files.update(fileId=file_id, body={"trashed": True},
                                    supportsAllDrives=True), "move the file to the trash")


def who(credentials) -> str:
    """
    The signed-in person's Google e-mail address, for "Scanned by" and the
    Log. Asked from Google Drive ("about me"); if that fails for any reason
    the Windows user name is used instead - the name is for information and
    must never stop a scan.
    """
    try:
        _, _, _, build = _libraries()
        about = build("drive", "v3", credentials=credentials, cache_discovery=False
                      ).about().get(fields="user(displayName,emailAddress)").execute()
        user = about.get("user", {})
        name = user.get("emailAddress") or user.get("displayName") or ""
        if name:
            return name
    except Exception:
        pass
    import getpass
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def _reason(exc: Exception) -> str:
    """A short, plain reason from a Google error."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in (403, "403"):
        return "this Google account is not allowed to open it (ask for it to be shared)."
    if status in (404, "404"):
        return "the sheet was not found (check the link)."
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:200]
