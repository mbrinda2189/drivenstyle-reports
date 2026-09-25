"""
main.py - Start the Drive N Style Reports desktop tool
======================================================

Run with:
    python main.py

What happens at start-up:
    1. High-DPI scaling is left to Qt 6's defaults, so the UI stays sharp on
       laptop screens set to 125% / 150% scaling.
    2. A QApplication is created with the Fusion style (a clean, neutral
       base that our stylesheet then themes consistently on every Windows
       version).
    3. The Segoe UI font and the professional-blue stylesheet from
       app/theme.py are applied to the whole application.
    4. The main window is created and shown.
"""

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app import __app_name__, __version__
from app.main_window import MainWindow
from app.theme import Fonts, build_stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Drive N Style")
    app.setStyle("Fusion")
    app.setFont(QFont(Fonts.FAMILY, Fonts.BASE))
    app.setStyleSheet(build_stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
