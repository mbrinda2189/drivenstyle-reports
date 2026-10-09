# Drive N Style - web tool (`web/`)

**Status: v0.22.0 - folders and plan only. No web code yet.**

## Why

The client's IT does not allow the Windows programs (the monthly reports
tool and the daily payout app) to run on the office PCs. Both therefore
move into ONE web tool, opened in the browser and hosted on the client's
own AWS account (Brinda, 09-10-2026). The desktop programs in `app/` and
`payout_app/` stay in the repository as they are, as the reference.

## The one rule: the figures do not change

The calculations are NOT rewritten. The web tool imports the same Python
code the desktop tool uses:

| Used as it is | What it does |
|---|---|
| `app/data/` | database, masters with dated rates, Zoho export reader, invoice PDF reader, matching, Scan review fixes, monthly inputs, audit log |
| `app/reports/` | the month's figures, the Excel workbook, the PDF version, the delivery (RTO) reports, the trend |
| `payout_app/engine.py` | invoice PDFs -> labour / spot incentive / internal team payout lines |
| `payout_app/slip.py` | the payout slip |

There is no `core/` folder: `app/data` and `app/reports` ARE the shared
rules (agreed 05-10-2026, confirmed again 09-10-2026). September 2026 is
saved as the "before" picture (`python scripts/snapshot_month.py 2026 9`)
and `tests/test_baseline.py` fails if any figure moves.

## Folders

```
web/
├── backend/    FastAPI (Python): sign-in, uploads, the database, and the
│               calls into app/data, app/reports and payout_app/engine
└── frontend/   React: the screens, in the same blue theme
```

## Decisions (Brinda, 09-10-2026)

| Subject | Decision |
|---|---|
| Hosting | One small server on the client's AWS, Mumbai region (ap-south-1), HTTPS on a web address of theirs. Brinda deploys; credentials awaited from the client. |
| Screens | React instead of PySide6 |
| Database | SQLite on the server (the data code and its tests are written for it), nightly backup to S3. Not PostgreSQL. |
| Masters | In the database, edited on the Masters screen, Excel import / export, dated rates. No masters Google Sheet. |
| Payout register | Database tables with Excel export. No register Google Sheet; the same rules (post once, In review, Re-issued, Cancelled, payment and proof). |
| Payment proofs | S3 bucket on the client's AWS. No Google Drive folder. |
| Sign-in | Google sign-in with roles: admin (Brinda, the client) and staff. Built so that user name + password can replace it if IT blocks Google. |
| Invoices | Uploaded in the browser. Monthly tool: Zoho invoice export, payments export, delivery (RTO) list. Daily payouts: invoice PDFs; an invoice already posted is skipped. |
| PDF of the reports | LibreOffice on the server (Excel cannot run there). Its pages must be compared with the present PDF before it is accepted. |
| Audit log | Records the signed-in person's e-mail instead of the Windows user name. |

Unchanged from the payout plan: no technician, the spot incentive rule, no
back-posting, no daily rounding of incentive, and every control.

## Build order

| Step | Version | What |
|---|---|---|
| 1 | v0.22.0 | **Done.** Tests as the baseline, September figures saved, these folders, the plan written down |
| 2 | | Backend base: FastAPI project, database on the server, sign-in and roles |
| 3 | | Masters: screens, Excel import, dated rates, checks, audit log |
| 4 | | Monthly tool: upload and read, Scan review, Monthly inputs, generate workbook and PDF, History |
| 5 | | Daily payouts: scan and review, posting to the register, mark paid with proof, audit log |
| 6 | | Payout slip, summary, and the month check against the monthly Labour and Spot incentive reports |
| 7 | | Deployment on the client's AWS: HTTPS, backups, deployment guide |

Each step is confirmed with Brinda before it is coded, and is one version.

## Still open

- AWS credentials from the client: an IAM user for Brinda (not the root
  login) allowed to create one small server and one S3 bucket.
- A web address for the tool (a sub-domain of the client's site).
- Whether the client's IT limits the websites staff can open, and whether
  Google sign-in is allowed there.
