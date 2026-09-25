"""
theme.py - Visual theme for the whole application
==================================================

WHAT THIS MODULE DOES
---------------------
Defines the single source of truth for the tool's look and feel:

1. `Colors`   - a named palette (professional blue theme). Every colour used
                anywhere in the app should come from here, so the client's
                colours can be changed in one place.
2. `Fonts`    - the font family and sizes. Segoe UI is used because it is the
                native Windows font: it renders crisply and makes the tool
                feel like a proper Windows application.
3. `build_stylesheet()` - returns one Qt Style Sheet (QSS - similar to CSS)
                that styles every standard widget: buttons, inputs, tables,
                tabs, scroll bars, combo boxes, etc.

HOW IT IS USED
--------------
`main.py` calls `app.setStyleSheet(build_stylesheet())` once at start-up.
Individual widgets pick up styles through their `objectName` (e.g. a
QPushButton with objectName "PrimaryButton" gets the filled blue style).

Object names used in the stylesheet
-----------------------------------
    Sidebar, SidebarButton, BrandTitle, BrandSubtitle, SidebarFooter
    PageTitle, PageSubtitle, SectionTitle, Muted, Card, StepBadge
    PrimaryButton, SecondaryButton, GhostButton, DangerButton
    StatValue, StatLabel, Toast
"""


import sys
from pathlib import Path


def asset(name: str) -> str:
    """
    Return the full path to a file in app/assets, with forward slashes
    (Qt stylesheets need forward slashes even on Windows).

    When running as a PyInstaller .exe, files are unpacked to a temporary
    folder given by sys._MEIPASS, so that location is used instead.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return (base / "app" / "assets" / name).as_posix()


class Colors:
    """Named colour palette. Hex strings so they can be used in QSS and QColor."""

    # --- Brand blues -------------------------------------------------------
    NAVY = "#0B2545"          # Sidebar background - deep, trustworthy navy
    NAVY_LIGHT = "#13335F"    # Sidebar hover background
    BLUE = "#1F5FBF"          # Primary action colour (buttons, highlights)
    BLUE_HOVER = "#2C6FD6"    # Primary button hover
    BLUE_PRESSED = "#184C99"  # Primary button pressed
    SKY = "#3B82F6"           # Active/focus accent
    BLUE_TINT = "#E8F0FC"     # Very light blue for selected rows / badges

    # --- Neutrals ----------------------------------------------------------
    BG = "#F4F7FB"            # Page background (pale grey-blue)
    SURFACE = "#FFFFFF"       # Cards, tables, inputs
    LINE = "#DCE4EF"          # Borders and dividers
    LINE_STRONG = "#C3CFDF"   # Input borders
    INK = "#1B2A41"           # Main text
    SLATE = "#5B6B82"         # Secondary text
    FAINT = "#8A99AE"         # Placeholder / disabled text
    SIDEBAR_TEXT = "#B8C7DD"  # Inactive sidebar text

    # --- Status ------------------------------------------------------------
    GREEN = "#1E8E5A"
    GREEN_TINT = "#E3F4EC"
    AMBER = "#B7791F"
    AMBER_TINT = "#FBF1DE"
    RED = "#C0392B"
    RED_TINT = "#FBE7E4"


class Fonts:
    """Font settings. Sizes are in points."""

    FAMILY = "Segoe UI"
    BASE = 10          # Normal body text
    SMALL = 9          # Captions, table headers
    SECTION = 12       # Card titles
    TITLE = 18         # Page titles
    STAT = 20          # Large numbers on stat tiles


def build_stylesheet() -> str:
    """
    Build and return the application-wide Qt stylesheet.

    The stylesheet is assembled with an f-string so every colour comes from
    the `Colors` palette above. Nothing else in the app should hard-code a
    colour, except where a colour is animated in code (see widgets/common.py).
    """
    c = Colors
    f = Fonts
    return f"""
    /* ---------- Global defaults ------------------------------------- */
    QWidget {{
        font-family: "{f.FAMILY}";
        font-size: {f.BASE}pt;
        color: {c.INK};
    }}
    QMainWindow, QWidget#ContentArea, QStackedWidget#PageStack, QScrollArea,
    QWidget#PageBody {{
        background: {c.BG};
    }}
    QToolTip {{
        background: {c.NAVY};
        color: white;
        border: none;
        padding: 6px 8px;
        border-radius: 4px;
    }}

    /* ---------- Sidebar ----------------------------------------------- */
    QFrame#Sidebar {{
        background: {c.NAVY};
    }}
    QLabel#BrandTitle {{
        color: white;
        font-size: 15pt;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    QLabel#BrandSubtitle {{
        color: {c.SIDEBAR_TEXT};
        font-size: {f.SMALL}pt;
    }}
    QLabel#SidebarFooter {{
        color: {c.FAINT};
        font-size: {f.SMALL}pt;
    }}
    QPushButton#SidebarButton {{
        background: transparent;
        color: {c.SIDEBAR_TEXT};
        border: none;
        border-left: 3px solid transparent;
        text-align: left;
        padding: 11px 18px;
        font-size: 10.5pt;
    }}
    QPushButton#SidebarButton:hover {{
        background: {c.NAVY_LIGHT};
        color: white;
    }}
    QPushButton#SidebarButton:checked {{
        background: {c.NAVY_LIGHT};
        color: white;
        border-left: 3px solid {c.SKY};
        font-weight: 600;
    }}

    /* ---------- Page headings ----------------------------------------- */
    QLabel#PageTitle {{
        font-size: {f.TITLE}pt;
        font-weight: 600;
        color: {c.INK};
    }}
    QLabel#PageSubtitle, QLabel#Muted {{
        color: {c.SLATE};
    }}
    QLabel#SectionTitle {{
        font-size: {f.SECTION}pt;
        font-weight: 600;
    }}
    QFrame#Card QLabel#StepBadge, QLabel#StepBadge {{
        background: {c.BLUE};
        color: white;
        border-radius: 12px;
        font-weight: 700;
        min-width: 24px; max-width: 24px;
        min-height: 24px; max-height: 24px;
        qproperty-alignment: AlignCenter;
    }}
    QFrame#Card QLabel#StepBadgeDone, QLabel#StepBadgeDone {{
        background: {c.GREEN};
        color: white;
        border-radius: 12px;
        font-weight: 700;
        min-width: 24px; max-width: 24px;
        min-height: 24px; max-height: 24px;
        qproperty-alignment: AlignCenter;
    }}

    /* ---------- Cards -------------------------------------------------- */
    QFrame#Card {{
        background: {c.SURFACE};
        border: 1px solid {c.LINE};
        border-radius: 10px;
    }}
    QFrame#Card QLabel {{
        background: transparent;
    }}
    QLabel#StatValue {{
        font-size: {f.STAT}pt;
        font-weight: 600;
    }}
    QLabel#StatLabel {{
        color: {c.SLATE};
    }}

    /* ---------- Buttons ------------------------------------------------ */
    /* PrimaryButton colours are animated in code (AnimatedButton); the
       rules here give shape and the disabled look. */
    QPushButton#PrimaryButton {{
        color: white;
        border: none;
        border-radius: 6px;
        padding: 9px 22px;
        font-weight: 600;
    }}
    QPushButton#PrimaryButton:disabled {{
        background: {c.LINE};
        color: {c.FAINT};
    }}
    QPushButton#SecondaryButton {{
        background: {c.SURFACE};
        color: {c.BLUE};
        border: 1px solid {c.BLUE};
        border-radius: 6px;
        padding: 8px 18px;
        font-weight: 600;
    }}
    QPushButton#SecondaryButton:hover {{
        background: {c.BLUE_TINT};
    }}
    QPushButton#SecondaryButton:pressed {{
        background: #D6E4FA;
    }}
    QPushButton#SecondaryButton:disabled {{
        color: {c.FAINT};
        border-color: {c.LINE};
    }}
    QPushButton#GhostButton {{
        background: transparent;
        color: {c.BLUE};
        border: none;
        border-radius: 6px;
        padding: 6px 10px;
        font-weight: 600;
    }}
    QPushButton#GhostButton:hover {{
        background: {c.BLUE_TINT};
    }}
    QPushButton#DangerButton {{
        background: transparent;
        color: {c.RED};
        border: 1px solid {c.RED_TINT};
        border-radius: 6px;
        padding: 6px 12px;
    }}
    QPushButton#DangerButton:hover {{
        background: {c.RED_TINT};
    }}

    /* ---------- Inputs ------------------------------------------------- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
        background: {c.SURFACE};
        border: 1px solid {c.LINE_STRONG};
        border-radius: 6px;
        padding: 7px 10px;
        selection-background-color: {c.BLUE};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QDateEdit:focus {{
        border: 1px solid {c.SKY};
    }}
    QLineEdit:read-only {{
        background: {c.BG};
        color: {c.SLATE};
    }}
    QComboBox::drop-down, QDateEdit::drop-down {{
        border: none;
        width: 26px;
    }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{
        image: url("{asset('chevron-down.svg')}");
        width: 12px; height: 12px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 20px;
        border: none;
        background: transparent;
    }}
    QSpinBox::up-arrow {{
        image: url("{asset('chevron-up.svg')}");
        width: 10px; height: 10px;
    }}
    QSpinBox::down-arrow {{
        image: url("{asset('chevron-down.svg')}");
        width: 10px; height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background: {c.SURFACE};
        border: 1px solid {c.LINE};
        selection-background-color: {c.BLUE_TINT};
        selection-color: {c.INK};
        outline: none;
        padding: 4px;
    }}
    QCheckBox {{
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {c.LINE_STRONG};
        border-radius: 4px;
        background: {c.SURFACE};
    }}
    QCheckBox::indicator:checked {{
        background: {c.BLUE};
        border: 1px solid {c.BLUE};
        image: url("{asset('check.svg')}");
    }}
    QCheckBox::indicator:hover {{
        border: 1px solid {c.SKY};
    }}

    /* ---------- Tables ------------------------------------------------- */
    QTableWidget, QTableView {{
        background: {c.SURFACE};
        alternate-background-color: #F8FAFD;
        border: 1px solid {c.LINE};
        border-radius: 8px;
        gridline-color: transparent;
        selection-background-color: {c.BLUE_TINT};
        selection-color: {c.INK};
        outline: none;
    }}
    QTableWidget::item, QTableView::item {{
        padding: 6px 8px;
        border-bottom: 1px solid #EEF2F7;
    }}
    QTableWidget::item:hover, QTableView::item:hover {{
        background: #F0F5FD;
    }}
    QHeaderView::section {{
        background: #F1F5FA;
        color: {c.SLATE};
        font-weight: 600;
        font-size: {f.SMALL}pt;
        border: none;
        border-bottom: 1px solid {c.LINE};
        padding: 8px;
    }}
    QTableCornerButton::section {{
        background: #F1F5FA;
        border: none;
    }}

    /* ---------- Tabs --------------------------------------------------- */
    QTabWidget::pane {{
        border: none;
        background: transparent;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {c.SLATE};
        padding: 10px 18px;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 600;
    }}
    QTabBar::tab:hover {{
        color: {c.BLUE};
    }}
    QTabBar::tab:selected {{
        color: {c.BLUE};
        border-bottom: 2px solid {c.BLUE};
    }}

    /* ---------- Progress bar ------------------------------------------ */
    QProgressBar {{
        background: #E6ECF4;
        border: none;
        border-radius: 5px;
        height: 10px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 {c.BLUE}, stop:1 {c.SKY});
        border-radius: 5px;
    }}

    /* ---------- Lists (scan log) -------------------------------------- */
    QListWidget {{
        background: {c.SURFACE};
        border: 1px solid {c.LINE};
        border-radius: 8px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 5px 6px;
    }}

    /* ---------- Scroll bars (thin, modern) ----------------------------- */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #C9D4E3;
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c.FAINT};
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: #C9D4E3;
        border-radius: 3px;
        min-width: 30px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none;
        border: none;
        width: 0; height: 0;
    }}

    /* ---------- Dialogs & toast ---------------------------------------- */
    QDialog {{
        background: {c.SURFACE};
    }}
    QLabel#Toast {{
        background: {c.NAVY};
        color: white;
        border-radius: 8px;
        padding: 12px 18px;
    }}
    """
