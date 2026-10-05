"""
build_payout_app.py - Build the daily payout app for the staff PCs
==================================================================

WHAT THIS SCRIPT DOES
---------------------
Run on Brinda's Windows PC, from the project folder, inside the virtual
environment:

    pip install -r requirements-dev.txt        (once - brings PyInstaller)
    python scripts\\build_payout_app.py

It produces, under dist\\ :

    Drive N Style Payouts\\               the program folder for a staff PC
        Drive N Style Payouts.exe
        Staff guide.pdf
        _internal\\ ...                    Python, Qt and the app's files
    Drive N Style Payouts v<version>.zip  the same folder, zipped for copying

A staff PC needs NOTHING else installed - no Python, no libraries.

THE STEPS
---------
1. Collect the files that must travel with the app into build\\payout_bundle:
       client_secret_*.json   the app's Google key, from the data folder
                              (%LOCALAPPDATA%\\Drive N Style Reports) or the
                              project's "data" folder. NEVER committed to
                              Git; it only goes into the built program.
       payout_defaults.json   the links of the masters sheet and the payout
                              register set on THIS PC (payout_settings.json),
                              so the staff do not paste them.
   The build stops with a plain message if the key is missing; missing
   links only give a warning (staff would then paste them on Set-up).
2. Run PyInstaller on payout_main.py as a windowed program in a FOLDER
   (not one big .exe: a folder starts in a second or two and raises fewer
   antivirus false alarms). Only the payout app is followed, so the
   monthly tool's screens are not included. Added by hand, because
   PyInstaller cannot see them from the code:
       app/assets                         the theme's pictures
       payout_app/assets                  the window icon
       googleapiclient ... sheets.v4.json, drive.v3.json
                                          Google's description of the two
                                          services the app uses
       pdfminer's data files              character tables of the PDF reader
   Left out on purpose, to keep the folder small: Google's descriptions of
   its ~500 OTHER services (PyInstaller packs them all - about 100 MB -
   so they are removed from the built folder afterwards), and large
   libraries the app never uses that may happen to be installed on the
   build PC (pandas, numpy, scipy, matplotlib ...). The self-check in step
   4 reads a real PDF, so leaving one out by mistake would show there.
3. Write "Staff guide.pdf" from docs/payout_app_staff_guide.md.
4. Start the built program with --check (see payout_app/__main__.py): it
   opens the app unseen and confirms every needed file is inside. The
   findings are printed. A FAIL here means the build must not be given out.
5. Zip the folder.

GIVING IT TO A STAFF PC
-----------------------
Copy the zip, unzip it (for example to C:\\Drive N Style Payouts), make a
desktop shortcut to the .exe. First start: Windows shows "Windows protected
your PC" because the program is not signed - More info, Run anyway. Then
Set-up: Sign in, choose the invoice folder.
To UPDATE: replace the folder with the new one. Sign-in and settings are
kept - they live in the user's own data folder, not in the program folder.

Options:
    --no-check    skip step 4
    --no-zip      skip step 5
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import __version__  # noqa: E402
from app.data.paths import data_dir  # noqa: E402
from payout_app import settings  # noqa: E402

APP_NAME = "Drive N Style Payouts"
BUNDLE = ROOT / "build" / settings.BUNDLE_FOLDER
DIST = ROOT / "dist"
GUIDE = ROOT / "docs" / "payout_app_staff_guide.md"
GOOGLE_SERVICES = ("sheets.v4.json", "drive.v3.json")
# Never imported by the payout app (openpyxl: the monthly tool's Excel work).
NOT_NEEDED = ("openpyxl", "tkinter", "pandas", "numpy", "scipy", "matplotlib",
              "IPython", "pytest", "PyQt5", "PyQt6", "gi")


def say(text: str = "") -> None:
    print(text, flush=True)


def collect_bundle() -> list[str]:
    """Step 1. Returns warnings; raises SystemExit if the key is missing."""
    warnings = []
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    BUNDLE.mkdir(parents=True)
    keys = []
    for folder in (data_dir(), ROOT / "data"):
        keys = sorted(folder.glob("client_secret*.json")) if folder.is_dir() else []
        if keys:
            break
    if not keys:
        raise SystemExit(
            "The app's Google key file (client_secret_....json) was not found in\n"
            f"  {data_dir()}\n  {ROOT / 'data'}\nThe app cannot sign in without it. "
            "Nothing was built.")
    shutil.copy2(keys[0], BUNDLE / keys[0].name)
    say(f"  Google key:   {keys[0].name}")
    saved = settings.load()
    links = {k: saved[k] for k in settings.DEFAULT_KEYS if saved.get(k)}
    (BUNDLE / settings.DEFAULTS_FILE).write_text(json.dumps(links, indent=2),
                                                 encoding="utf-8")
    for label, key in (("Masters sheet", "masters_sheet_url"),
                       ("Payout register", "register_sheet_url")):
        if links.get(key):
            say(f"  {label + ':':<16}{links[key]}")
        else:
            warnings.append(f"{label}: no link is set on this PC, so none is built "
                            "in - staff will have to paste it on Set-up.")
    return warnings


def pyinstaller_arguments() -> list[str]:
    """Step 2: what PyInstaller is asked to do."""
    import googleapiclient
    documents = Path(googleapiclient.__file__).parent / "discovery_cache" / "documents"
    missing = [n for n in GOOGLE_SERVICES if not (documents / n).is_file()]
    if missing:
        raise SystemExit(f"Google's library is missing {', '.join(missing)} - "
                         "run  pip install -r requirements.txt  again.")
    sep = os.pathsep                       # ";" on Windows, ":" elsewhere
    arguments = [
        str(ROOT / "payout_main.py"),
        "--name", APP_NAME, "--windowed", "--noconfirm", "--clean",
        "--distpath", str(DIST), "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
        "--icon", str(ROOT / "payout_app" / "assets" / "payouts.ico"),
        "--add-data", f"{ROOT / 'app' / 'assets'}{sep}app/assets",
        "--add-data", f"{ROOT / 'payout_app' / 'assets'}{sep}payout_app/assets",
        "--add-data", f"{BUNDLE}{sep}{settings.BUNDLE_FOLDER}",
        "--collect-data", "pdfminer",
    ]
    for module in NOT_NEEDED:
        arguments += ["--exclude-module", module]
    for name in GOOGLE_SERVICES:
        arguments += ["--add-data",
                      f"{documents / name}{sep}googleapiclient/discovery_cache/documents"]
    return arguments


def prune_google_documents(folder: Path) -> float:
    """Remove the descriptions of Google services the app does not use. MB freed."""
    freed = 0
    for documents in folder.rglob("discovery_cache/documents"):
        for f in documents.glob("*.json"):
            if f.name not in GOOGLE_SERVICES:
                freed += f.stat().st_size
                f.unlink()
    return freed / 1_048_576


def write_guide(folder: Path) -> None:
    """Step 3: the staff guide as a PDF, made with Qt (no other program)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import (
        QFont, QGuiApplication, QPageLayout, QPageSize, QPdfWriter, QTextDocument)
    app = QGuiApplication.instance() or QGuiApplication([])
    writer = QPdfWriter(str(folder / "Staff guide.pdf"))
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                     QMarginsF(16, 14, 16, 14), QPageLayout.Millimeter))
    document = QTextDocument()
    document.setDefaultFont(QFont("Segoe UI", 10))
    document.setMarkdown(GUIDE.read_text(encoding="utf-8"))
    document.print_(writer)
    del app


def program_path(folder: Path) -> Path:
    return folder / (APP_NAME + (".exe" if os.name == "nt" else ""))


def run_check(folder: Path) -> bool:
    """Step 4: let the built program check itself."""
    result = ROOT / "build" / "payout_check.txt"
    result.unlink(missing_ok=True)
    env = dict(os.environ)
    if os.name != "nt":
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        done = subprocess.run([str(program_path(folder)), "--check", str(result)],
                              env=env, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        say(f"  FAIL The built program did not run: {exc}")
        return False
    if result.is_file():
        for line in result.read_text(encoding="utf-8").splitlines():
            say("  " + line)
    else:
        say("  FAIL The built program gave no answer.")
    return done.returncode == 0 and result.is_file()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the daily payout app.")
    parser.add_argument("--no-check", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    options = parser.parse_args()
    try:
        import PyInstaller.__main__ as pyinstaller
    except ImportError:
        say("PyInstaller is not installed. Run:  pip install -r requirements-dev.txt")
        return 1

    say(f"Building {APP_NAME} v{__version__}")
    say("\n1. Files that travel with the app")
    warnings = collect_bundle()

    say("\n2. Building the program (this takes a few minutes) ...")
    pyinstaller.run(pyinstaller_arguments())
    folder = DIST / APP_NAME
    if not program_path(folder).is_file():
        say("The program was not produced - see PyInstaller's messages above.")
        return 1

    say(f"  {prune_google_documents(folder):.0f} MB of unused Google files removed")

    say("\n3. Staff guide")
    try:
        write_guide(folder)
        say("  Staff guide.pdf written")
    except Exception as exc:                          # the app itself is fine
        warnings.append(f"The staff guide PDF could not be made ({exc}).")

    ok = True
    if not options.no_check:
        say("\n4. The built program checks itself")
        ok = run_check(folder)

    archive = None
    if ok and not options.no_zip:
        say("\n5. Zipping")
        archive = shutil.make_archive(str(DIST / f"{APP_NAME} v{__version__}"), "zip",
                                      root_dir=DIST, base_dir=APP_NAME)
        say(f"  {archive}")

    say()
    for warning in warnings:
        say(f"Note: {warning}")
    if not ok:
        say("THE BUILD FAILED ITS CHECK - do not give it to the staff. Send the "
            "lines above to Claude.")
        return 1
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1_048_576
    say(f"Done: {folder}  ({size:.0f} MB)")
    if archive:
        say("Copy the zip to a staff PC, unzip it, and make a desktop shortcut to "
            f"“{APP_NAME}.exe”.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
