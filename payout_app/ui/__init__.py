"""
payout_app.ui - The screens of the daily payout app
===================================================

Qt (PySide6) code only lives in this package; everything the screens DO is
in payout_app/service.py, so it can be tested without a screen. The look
(colours, fonts, cards, buttons, sidebar) is the monthly tool's own
(app/theme.py, app/widgets) - the client asked for one professional blue
look, and one theme file keeps both apps the same.

    main_window.py   the window: sidebar, pages, running slow work in the
                     background, messages
    workers.py       running one slow action (Google, reading PDFs) on a
                     background thread so the window never freezes
    setup_page.py    Set-up: Google sign-in, the two sheets, invoice folder
    scan_page.py     Scan: the daily run and what it did
    review_page.py   Review: names that hold invoices up, and their fixes
Still to come: Payouts (recording payments and proofs) and History.
"""
