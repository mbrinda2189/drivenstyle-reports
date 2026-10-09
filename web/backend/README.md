# web/backend - the server (FastAPI)

**Nothing here yet (v0.22.0). Step 2 of the plan in `web/README.md`.**

This folder will hold the server program: sign-in and roles, file uploads,
the database on the server, and the web addresses the screens call. It will
not contain any calculation of its own - sales, cost, labour, incentive and
the workbook all come from `app/data`, `app/reports` and
`payout_app/engine.py`, imported as they are.
