"""
workers.py - Run one slow action in the background
==================================================

WHAT THIS MODULE DOES
---------------------
Talking to Google and reading a folder of PDFs take seconds. Done on the
screen's own thread, the window would freeze and Windows would show "Not
responding". `start(...)` runs one function on a background thread and
reports back on the screen's thread:

    on_progress(done, total, text)   while it works (reading PDFs)
    on_done(result)                  the function's return value
    on_failed(message)               a message to show the user

The function receives one argument: a `progress(done, total, text)` call it
may use or ignore. A GoogleError's text is shown as it is (it was written
for the user); any other error is shown with a short lead-in so nothing
fails silently.

Only ONE task runs at a time (the main window sees to it): the Google
connection must not be used by two threads at once.

TWO THINGS THAT MUST STAY AS THEY ARE (both were crashes while testing)
-----------------------------------------------------------------------
1. Callbacks go through `_Relay`. A Qt signal connected to a plain Python
   function is run in the thread that EMITTED it - here the background
   thread - and touching a label or table from there crashes Qt sooner or
   later. A signal connected to a slot of a QObject is delivered in that
   object's thread; the relay lives on the screen's thread.
2. The background thread is a `Task(QThread)` object that itself lives on
   the screen's thread and is only ever deleted there, after it has fully
   stopped (`wait()`). An earlier version moved a separate worker object
   INTO the thread and deleted it when the thread finished; now and then
   Python and Qt then both destroyed it, from two threads - a crash once
   in a few runs.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from payout_app.google_api import GoogleError

# Tasks that are running. A page's on_done may start the next task at once,
# while the previous thread is still closing down; every task is held here
# until its own thread has stopped.
_RUNNING: set = set()


class Task(QThread):
    """One function, run on a background thread."""

    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent: QObject | None = None):
        super().__init__(parent)
        self.function = function

    def run(self) -> None:                              # runs on the new thread
        try:
            result = self.function(self.progress.emit)
        except GoogleError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                        # never fail silently
            self.failed.emit(f"Something went wrong: {exc.__class__.__name__}: {exc}")
        else:
            self.done.emit(result)


class _Relay(QObject):
    """Receives a Task's signals on the screen's thread and passes them on."""

    def __init__(self, owner: QObject, task: Task, on_done, on_failed, on_progress):
        super().__init__(owner)
        self.task = task
        self._on_done, self._on_failed, self._on_progress = on_done, on_failed, on_progress

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
        """The thread has ended: let it stop completely, then tidy up."""
        self.task.wait()
        _RUNNING.discard(self)
        self.task.deleteLater()
        self.deleteLater()


def start(owner: QObject, function, on_done, on_failed, on_progress=None) -> Task:
    """
    Run `function(progress)` in the background. `owner` must live on the
    screen's thread; the callbacks are run there.
    """
    task = Task(function, owner)
    relay = _Relay(owner, task, on_done, on_failed, on_progress)
    task.done.connect(relay.done)
    task.failed.connect(relay.failed)
    task.progress.connect(relay.progress)
    task.finished.connect(relay.finished)
    _RUNNING.add(relay)
    task.start()
    return task
