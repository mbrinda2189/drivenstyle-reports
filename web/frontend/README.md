# web/frontend - the screens (React + TypeScript)

**v0.26.0: sign-in page, the frame with the two tabs, Users, Masters (with
Excel import / export), Audit log and the four monthly screens.** The other screens show "Comes in step N" until they are built.

| File | What it does |
|---|---|
| `src/App.tsx` | Signed in or not; the address of every screen; what each role may open |
| `src/Shell.tsx` | The frame: top bar with the Daily payouts / Monthly reports tabs, left menu, Shared (admin) section |
| `src/api.ts` | The only file that talks to the server |
| `src/theme.css` | Every colour and size - the desktop tool's blue theme (`app/theme.py`) |
| `src/pages/SignIn.tsx` | Google sign-in, and the test sign-in on a developer's PC |
| `src/pages/Masters.tsx` | The five masters: table, filters, bulk actions and the edit form with rate history |
| `src/pages/ImportDialog.tsx` | Import a sheet: sheet chooser, column matching, preview, result, Zoho's missing items |
| `src/month.tsx` | The month being worked on (shared by the monthly screens), the Month / Year picker, the type-to-find box |
| `src/pages/Generate.tsx` | Generate reports: the month's files, Read invoices, Generate workbook, download |
| `src/pages/ScanReview.tsx` | Issues with their fixes, Saved matches, Invoices read |
| `src/pages/MonthlyInputs.tsx` | Indirect costs, high-profit threshold, automatic cost percentages |
| `src/pages/History.tsx` | Workbooks made and months read: download, PDF, regenerate, remove |
| `src/pages/AuditLog.tsx` | The audit log with filters and Excel export (admin) |
| `src/pages/Users.tsx` | The users list (admin) |
| `src/pages/ComingSoon.tsx` | Placeholder for a screen not built yet |

```powershell
npm install        # once, and after package.json changes
npm run dev        # screens at http://localhost:5173 (the server must run on port 8000)
npm run build      # checks the TypeScript and writes dist/ for the real server
```

`node_modules/` and `dist/` are not in Git - npm re-creates both.
