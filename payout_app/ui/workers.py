"""
workers.py - Run one slow action in the background
==================================================

WHAT THIS MODULE DOES
---------------------
Talking to Google and reading a folder of PDFs take seconds. Done on the
screen's own thread, the window would freeze and Windows would show "Not
responding". `Task` runs one function on a background thread and reports
back with signals, which Qt delivers on the screen's thread:

    progress(done, total, text)   while it works (reading PDFs)
    done(result)                  the function's return value
    failed(message)               a message to show the user

The function receives one argument: a `progress(done, total, text)` call it
may use or ignore. A GoogleError's text is shown as it is (it was written
for the user); any other error is shown with a short lead-in so nothing
fails silently.

Only ONE task runs at a time (the main window sees to it): the Google
connection must not be used by two threads at once.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from payout_app.google_api import GoogleError


class Task(QObject):
    """One function, run on a background thread."""

    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, function):
        super().__init__()
        self.function = function

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(self.progress.emit)
        except GoogleError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                       # never fail silently
            self.failed.emit(f"Something went wrong: {exc.__class__.__name__}: {exc}")
        else:
            self.done.emit(result)


# Tasks that are running. A finished page callback may start the next task
# at once, while the previous thread is still closing down; holding every
# running task here until ITS thread has finished keeps Python from
# destroying one too early.
_RUNNING: set = set()


class _Relay(QObject):
    """
    Receives a Task's signals ON THE SCREEN'S THREAD and passes them on.

    Why this exists: a signal connected to a plain Python function is run
    in the thread that emitted it - here the background thread - and
    touching a label or table from there crashes Qt sooner or later. A
    signal connected to a slot of a QObject is delivered in THAT object's
    thread. The relay is created on the screen's thread, so everything the
    pages do in `on_done` / `on_failed` / `on_progress` happens there.
    """

    def __init__(self, owner: QObject, on_done, on_failed, on_progress, on_finished):
        super().__init__(owner)
        self._on_done, self._on_failed = on_done, on_failed
        self._on_progress, self._on_finished = on_progress, on_finished

    @Slot(object)
    def done(self, result) -> None:
        self._on_done(result)

    @Slot(str)
    def failed(self, message: str) -> None:
        self._on_failed(message)

    @Slot(int, int, str)
    def progress(self, done: int, total: int, text: str) -> None:
        if self._on_progress:
            self._on_progress(done, total, text)

    @Slot()
    def finished(self) -> None:
        if self._on_finished:
            self._on_finished()
        _RUNNING.discard(self.keep)
        self.deleteLater()


def start(owner: QObject, function, on_done, on_failed, on_progress=None,
          on_finished=None) -> QThread:
    """
    Run `function(progress)` in the background. `owner` must live on the
    screen's thread; the callbacks are run there (see _Relay). The thread
    and task are kept alive until the work has finished (_RUNNING).
    """
    thread = QThread(owner)
    task = Task(function)
    relay = _Relay(owner, on_done, on_failed, on_progress, on_finished)
    task.moveToThread(thread)
    thread.started.connect(task.run)
    task.done.connect(relay.done)
    task.failed.connect(relay.failed)
    task.progress.connect(relay.progress)
    task.done.connect(thread.quit)
    task.failed.connect(thread.quit)
    thread.finished.connect(relay.finished)
    thread.finished.connect(task.deleteLater)
    thread.finished.connect(thread.deleteLater)
    relay.keep = (thread, task, relay)
    _RUNNING.add(relay.keep)
    thread.start()
    return thread
