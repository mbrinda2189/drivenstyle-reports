# web/backend - the server (FastAPI)

**v0.24.0: sign-in, roles, users, masters and the audit log.** Excel
import, reports and payouts come in steps 3b to 6 (`web/README.md`).

| File | What it does |
|---|---|
| `main.py` | The server: every `/api` address, who may open it, and serving the built screens |
| `masters_api.py` | Masters and audit log addresses - every rule comes from `app/data/masters_repo.py` |
| `bring_across.py` | One-time copy of the desktop tool's database into the web tool |
| `security.py` | Checking Google's sign-in answer; the signed sign-in cookie |
| `config.py` | The settings (environment variables) - data folder, first admins, Google client ID, test sign-in |
| `requirements.txt` | The server's packages (the desktop programs do not need them) |

The users list itself is `app/data/users_repo.py` (data layer, no web
code), in the same database as the masters: table `users`, schema step 13.

This folder holds no calculation of its own - sales, cost, labour,
incentive and the workbook all come from `app/data`, `app/reports` and
`payout_app/engine.py`, imported as they are.

Tests: `tests/test_web_auth.py`, `tests/test_web_masters.py` (Google is replaced by a stand-in; no
internet needed).
