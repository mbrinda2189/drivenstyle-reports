"""
fakes.py - Stand-ins for Google used by the payout app's tests
==============================================================

`FakeGoogle` keeps the masters sheet "M" and the payout register "R" as
lists of rows and offers the same calls as google_api.SheetsClient;
`FakeDrive` stands in for google_api.DriveClient and remembers what was
"uploaded". The tests therefore run the real service code, with no
internet and no client data.
"""

from pathlib import Path

from payout_app import register as rg


class FakeGoogle:
    def __init__(self, masters_tabs=None):
        self.store = {"M": masters_tabs or {}, "R": rg.new_register_tabs()}
        self.titles = {"M": "Drive N Style Masters", "R": "Drive N Style Payout Register"}

    def read_tabs(self, sheet_id):
        return {t: [list(r) for r in rows] for t, rows in self.store[sheet_id].items()}

    def tab_names(self, sheet_id):
        return list(self.store[sheet_id])

    def title(self, sheet_id):
        return self.titles[sheet_id]

    def append_rows(self, sheet_id, tab, rows):
        self.store[sheet_id][tab] += [list(r) for r in rows]

    def update_rows(self, sheet_id, updates):
        for tab, n, cells in updates:
            self._write(sheet_id, tab, n, 0, cells)

    def update_ranges(self, sheet_id, updates):
        for tab, cell, rows in updates:
            letters = "".join(c for c in cell if c.isalpha())
            first = int("".join(c for c in cell if c.isdigit()))
            column = 0
            for letter in letters:                       # "K" -> 10, "AA" -> 26
                column = column * 26 + (ord(letter.upper()) - 64)
            for offset, cells in enumerate(rows):
                self._write(sheet_id, tab, first + offset, column - 1, cells)

    def add_tab(self, sheet_id, title, rows):
        self.store[sheet_id][title] = [list(r) for r in rows]

    def clear_rows(self, sheet_id, tabs):
        for tab in tabs:
            del self.store[sheet_id][tab][1:]

    def _write(self, sheet_id, tab, row_number, column, cells):
        rows = self.store[sheet_id][tab]
        while len(rows) < row_number:
            rows.append([])
        row = rows[row_number - 1]
        row += [""] * (column + len(cells) - len(row))
        row[column:column + len(cells)] = cells


class FakeDrive:
    def __init__(self, owner=True, files=None):
        self.folders, self.uploads = {}, []
        self.owner, self.copies, self.trashed = owner, [], []
        self.files = files or []            # what list_named returns

    def copy(self, file_id, name):
        self.copies.append((file_id, name))
        return f"https://docs.google.com/spreadsheets/d/COPY{len(self.copies)}/edit"

    def owned_by_me(self, file_id):
        return self.owner

    def list_named(self, names):
        return [dict(f) for f in self.files
                if f["name"] in names and f["id"] not in self.trashed]

    def trash(self, file_id):
        self.trashed.append(file_id)

    def create_folder(self, name):
        folder_id = f"F{len(self.folders) + 1}"
        self.folders[folder_id] = name
        return folder_id, f"https://drive.google.com/drive/folders/{folder_id}"

    def folder_name(self, folder_id):
        return self.folders[folder_id]

    def upload(self, path, name, folder_id):
        self.uploads.append((Path(path).name, name, folder_id))
        return f"https://drive.google.com/file/d/{name}/view"
