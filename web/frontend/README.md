# web/frontend - the screens (React + TypeScript)

**v0.23.0: sign-in page, the frame with the two tabs, and the Users
screen.** The other screens show "Comes in step N" until they are built.

| File | What it does |
|---|---|
| `src/App.tsx` | Signed in or not; the address of every screen; what each role may open |
| `src/Shell.tsx` | The frame: top bar with the Daily payouts / Monthly reports tabs, left menu, Shared (admin) section |
| `src/api.ts` | The only file that talks to the server |
| `src/theme.css` | Every colour and size - the desktop tool's blue theme (`app/theme.py`) |
| `src/pages/SignIn.tsx` | Google sign-in, and the test sign-in on a developer's PC |
| `src/pages/Users.tsx` | The users list (admin) |
| `src/pages/ComingSoon.tsx` | Placeholder for a screen not built yet |

```powershell
npm install        # once, and after package.json changes
npm run dev        # screens at http://localhost:5173 (the server must run on port 8000)
npm run build      # checks the TypeScript and writes dist/ for the real server
```

`node_modules/` and `dist/` are not in Git - npm re-creates both.
