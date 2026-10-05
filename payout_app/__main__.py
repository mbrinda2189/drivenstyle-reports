"""
Start the daily payout app:   python -m payout_app

WHAT HAPPENS AT START-UP
------------------------
The same steps as the monthly tool's main.py - one Qt application, the
Fusion style, the shared font and stylesheet (app/theme.py) - then the
payout app's own window (payout_app/ui/main_window.py). Nothing is read
from Google until the user presses a button.
"""

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app import __version__
from app.theme import Fonts, build_stylesheet
from payout_app.ui.main_window import APP_NAME, MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
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
