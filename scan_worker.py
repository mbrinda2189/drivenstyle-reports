"""
scan_worker.py - Reads a folder of invoice PDFs in the background
=================================================================

WHAT THIS MODULE DOES
---------------------
Reading dozens of PDFs takes a few seconds. Doing it on the screen's own
thread would freeze the window, so `ScanWorker` runs in a separate thread
(QThread) and reports back with signals:

    progress(done, total, file_name, status, reason)   after each file
    finished(results)                                   list of FileResult

Only READING happens in the background (invoices_repo.classify_file is a
pure function). Saving to the database happens back on the main thread
when `finished` arrives, because a SQLite connection must stay on the
thread that opened it.

`cancel()` asks the worker to stop after the current file.

HOW TO USE (see generate_page.py)
---------------------------------
    thread = QThread()
    worker = ScanWorker(pdf_paths, year, month)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(...)          # store results, update screen
    thread.start()
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.data.invoices_repo import FileResult, classify_file


class ScanWorker(QObject):
    """Reads each PDF and classifies it (read / skipped / error)."""

    progress = Signal(int, int, str, str, str)
    finished = Signal(list)

    def __init__(self, paths: list[Path], year: int, month: int):
        super().__init__()
        self.paths = paths
        self.year, self.month = year, month
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @Slot()
    def run(self) -> None:
        results: list[FileResult] = []
        total = len(self.paths)
        for i, path in enumerate(self.paths, start=1):
            if self._cancelled:
                break
            result = classify_file(path, self.year, self.month)
            results.append(result)
            self.progress.emit(i, total, result.file_name, result.status, result.reason)
        self.finished.emit(results)