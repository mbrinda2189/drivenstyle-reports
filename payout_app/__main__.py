"""
Start the daily payout app:   python -m payout_app

WHAT HAPPENS AT START-UP
------------------------
The same steps as the monthly tool's main.py - one Qt application, the
Fusion style, the shared font and stylesheet (app/theme.py) - then the
payout app's own window (payout_app/ui/main_window.py). Nothing is read
from Google until the user presses a button.

WHEN SOMETHING GOES WRONG UNEXPECTEDLY (v0.18.0)
------------------------------------------------
The installed program has no command window, so an error nobody foresaw
would vanish without a trace. Instead it is written, with the date, to
"payout_app_errors.log" in the PC's data folder
(%LOCALAPPDATA%\\Drive N Style Reports) and a message box says so - the
staff can send that file.

SELF-CHECK (v0.18.0)
--------------------
    "Drive N Style Payouts.exe" --check result.txt
starts the app without showing it, checks that everything it needs
travelled with it - the screens, the theme's pictures, the Google key, the
PDF reader, Google's libraries for Sheets and Drive - writes the findings
to the file and ends with 0 (all fine) or 1. The build script runs this on
the freshly built program, so a missing file is found on Brinda's PC and
not on a staff PC.
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path


def _log_error(kind, value, trace) -> Path:
    from app.data.paths import data_dir
    path = data_dir() / "payout_app_errors.log"
    with path.open("a", encoding="utf-8") as out:
        out.write(f"\n--- {datetime.now():%d-%m-%Y %H:%M:%S} ---\n")
        out.write("".join(traceback.format_exception(kind, value, trace)))
    return path


def _excepthook(kind, value, trace) -> None:
    """An error nobody foresaw: keep it in the log file and tell the user."""
    try:
        path = _log_error(kind, value, trace)
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None, "Drive N Style Payouts",
                f"Something unexpected went wrong:\n\n{value}\n\nThe details were "
                f"saved in:\n{path}\n\nPlease send that file if it happens again.")
    except Exception:
        sys.__excepthook__(kind, value, trace)


def self_check() -> list[tuple[bool, str]]:
    """Is everything the app needs present? Returns (ok, what) lines."""
    lines: list[tuple[bool, str]] = []

    def check(what: str, test) -> None:
        try:
            detail = test()
            lines.append((True, f"{what}{': ' + str(detail) if detail else ''}"))
        except Exception as exc:
            lines.append((False, f"{what}: {exc.__class__.__name__}: {exc}"))

    def window():
        from payout_app.ui.main_window import MainWindow
        MainWindow().close()

    def pictures():
        from app.theme import asset
        missing = [n for n in ("check.svg", "chevron-down.svg", "chevron-up.svg")
                   if not Path(asset(n)).is_file()]
        if missing:
            raise FileNotFoundError(", ".join(missing))

    def google_key():
        from payout_app.google_api import find_client_secret
        return find_client_secret().name[:24] + "…"

    def google_libraries():
        import httplib2
        from googleapiclient.discovery import build
        for name, version in (("sheets", "v4"), ("drive", "v3")):
            build(name, version, http=httplib2.Http(), static_discovery=True)
        import google_auth_oauthlib.flow  # noqa: F401
        from googleapiclient.http import MediaFileUpload  # noqa: F401

    def pdf_reader():
        # Really read a PDF: one is written with Qt, then read back with the
        # same reader the invoices go through.
        import tempfile

        import pdfplumber
        from PySide6.QtGui import QPdfWriter, QTextDocument

        from payout_app import engine  # noqa: F401
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "check.pdf")
            document = QTextDocument()
            document.setPlainText("TAX INVOICE DNSCHECK0001")
            writer = QPdfWriter(path)
            document.print_(writer)
            del writer
            with pdfplumber.open(path) as pdf:
                words = [w["text"] for w in pdf.pages[0].extract_words()]
        if "DNSCHECK0001" not in words:
            raise ValueError(f"a test PDF was not read back correctly ({words[:5]})")
        return "a test PDF was written and read back"

    def sheet_links():
        from payout_app import settings
        found = [k for k in ("masters_sheet_id", "register_sheet_id") if settings.get(k)]
        if len(found) < 2:
            raise ValueError("the masters sheet / register links are not built in "
                             "(staff will have to paste them on Set-up)")
        return "built in"

    check("The app window opens", window)
    check("Theme pictures", pictures)
    check("Google key file", google_key)
    check("Google libraries (Sheets, Drive, sign-in, upload)", google_libraries)
    check("PDF reader", pdf_reader)
    check("Sheet links", sheet_links)
    return lines


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from app import __version__
    from app.theme import Fonts, build_stylesheet
    from payout_app.ui.main_window import APP_NAME, MainWindow

    sys.excepthook = _excepthook
    app = QApplication(argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Drive N Style")
    app.setStyle("Fusion")
    app.setFont(QFont(Fonts.FAMILY, Fonts.BASE))
    app.setStyleSheet(build_stylesheet())
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) \
        / "payout_app" / "assets" / "payouts.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    if "--check" in argv:
        lines = self_check()
        text = "\n".join(f"{'OK  ' if ok else 'FAIL'} {what}" for ok, what in lines)
        at = argv.index("--check")
        if at + 1 < len(argv):
            Path(argv[at + 1]).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0 if all(ok for ok, _ in lines) else 1

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
