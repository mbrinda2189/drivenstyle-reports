"""
animated_stack.py - Page container with smooth transitions
==========================================================

WHAT THIS MODULE DOES
---------------------
`AnimatedStack` is a QStackedWidget (it holds all pages but shows one at a
time) that animates the change of page:

    * the new page fades in from transparent to fully visible, and
    * at the same time it slides a short distance (24 px) into place.

The movement is short and quick (260 ms, ease-out) - enough to show the user
that the screen changed, without slowing them down. It only happens when the
user changes page, never on its own.

HOW TO USE
----------
    stack = AnimatedStack()
    stack.addWidget(page_a)
    stack.addWidget(page_b)
    stack.slide_to(1)          # animated switch to page_b

Set `AnimatedStack.animations_enabled = False` to make switching instant
(e.g. for users who prefer reduced motion).
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget


class AnimatedStack(QStackedWidget):
    """QStackedWidget that fades and slides between pages."""

    animations_enabled = True
    DURATION_MS = 260
    SLIDE_PX = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        # objectName lets the stylesheet give only this stack the page
        # background (QTabWidget also uses a QStackedWidget internally).
        self.setObjectName("PageStack")
        self._group: QParallelAnimationGroup | None = None
        self._animating_page = None

    def slide_to(self, index: int) -> None:
        """Switch to page `index` with a fade + slide animation."""
        if index == self.currentIndex():
            return

        # Finish any running transition immediately, so rapid clicks on the
        # sidebar never leave a page half-faded.
        if self._group is not None:
            self._group.stop()
            self._finish()

        new_page = self.widget(index)
        self.setCurrentIndex(index)

        if not self.animations_enabled:
            return

        # Opacity effect on the incoming page (0 -> 1).
        effect = QGraphicsOpacityEffect(new_page)
        effect.setOpacity(0.0)
        new_page.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity")
        fade.setDuration(self.DURATION_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        # Slide: start slightly to the right, glide to the final position.
        end_pos = QPoint(0, 0)
        slide = QPropertyAnimation(new_page, b"pos")
        slide.setDuration(self.DURATION_MS)
        slide.setStartValue(end_pos + QPoint(self.SLIDE_PX, 0))
        slide.setEndValue(end_pos)
        slide.setEasingCurve(QEasingCurve.OutCubic)

        self._group = QParallelAnimationGroup(self)
        self._group.addAnimation(fade)
        self._group.addAnimation(slide)
        self._group.finished.connect(self._finish)
        self._animating_page = new_page
        self._group.start()

    def _finish(self) -> None:
        """
        Clean up when the animation ends.

        The temporary opacity effect is removed (a page left with a graphics
        effect renders more slowly) and the page is snapped to its exact
        final position.
        """
        page = self._animating_page
        if page is not None:
            page.setGraphicsEffect(None)
            page.move(0, 0)
        self._group = None
        self._animating_page = None
