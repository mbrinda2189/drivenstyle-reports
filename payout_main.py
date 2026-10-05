"""
payout_main.py - Entry point of the daily payout app for the Windows build
==========================================================================

PyInstaller needs one plain script to start from; `python -m payout_app`
has none. This file only hands over to payout_app/__main__.py, where the
start-up is explained. During development either works:

    python -m payout_app
    python payout_main.py
"""

import sys

from payout_app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
