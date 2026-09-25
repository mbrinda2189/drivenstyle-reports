"""
pages - One module per screen of the tool
=========================================

    base.py            - ScrollPage: common scrollable page frame (margins,
                         header, helper to show toast messages).
    generate_page.py   - Generate reports: month, invoice folder, payments
                         export, output folder, report list, scan + generate.
    review_page.py     - Scan review: issues found in the invoices, with a
                         control on each row to fix or confirm it.
    masters_page.py    - Masters: cost sheet, labour charges, packages,
                         executives & incentive - editable, with effective
                         dates for rate changes.
    inputs_page.py     - Monthly inputs: indirect costs and the high-profit
                         threshold for the month.
    history_page.py    - History: months already processed.
"""
