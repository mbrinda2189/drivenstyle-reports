/*
 * App.tsx - Signed in or not, and which screen
 * ============================================
 *
 * WHAT THIS FILE DOES
 * -------------------
 * 1. On opening, asks the server "who is signed in?" (api.me).
 *      nobody  -> the sign-in page
 *      someone -> the tool (Shell) with the screens their role allows
 * 2. Lists every screen's address.
 *
 * THE TWO TABS (layout approved by Brinda, 09-10-2026)
 *      Daily payouts     /daily/...     staff and admin
 *      Monthly reports   /monthly/...   admin only
 *      Shared            /masters       staff and admin (v0.24.0)
 *      Admin             /admin/...     admin only (Audit log, Users)
 *
 * A staff member who types a /monthly or /admin address is sent back to
 * the daily payouts. That is only for tidiness: the real control is on the
 * server, which refuses the data itself (web/backend/main.py).
 *
 * Every screen is real from v0.27.0 (monthly from v0.26.0, daily payouts
 * from v0.27.0).
 */
import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { ApiError, Config, User, api } from "./api";
import Shell from "./Shell";
import AuditLog from "./pages/AuditLog";
import DailyHistory from "./pages/DailyHistory";
import DailyReview from "./pages/DailyReview";
import DailyScan from "./pages/DailyScan";
import DailySummary from "./pages/DailySummary";
import Generate from "./pages/Generate";
import History from "./pages/History";
import Masters from "./pages/Masters";
import MonthlyInputs from "./pages/MonthlyInputs";
import Payouts from "./pages/Payouts";
import ScanReview from "./pages/ScanReview";
import SignIn from "./pages/SignIn";
import Users from "./pages/Users";

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setConfig(await api.config());
        setUser(await api.me());
      } catch (error) {
        // 401 simply means "nobody is signed in yet" - not a problem.
        if (alive && !(error instanceof ApiError && error.status === 401)) {
          setProblem(error instanceof Error ? error.message : "Something went wrong.");
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const signOut = useCallback(async () => {
    await api.signOut().catch(() => undefined);
    setUser(null);
  }, []);

  /** Called by a screen when the server says the sign-in is no longer valid. */
  const expired = useCallback(() => setUser(null), []);

  if (loading) return <div className="center-note">Opening…</div>;
  if (!config) return <div className="center-note">{problem || "The server did not answer."}</div>;
  if (!user) return <SignIn config={config} onSignedIn={setUser} />;

  const admin = user.role === "admin";
  return (
    <Routes>
      <Route element={<Shell user={user} version={config.version} onSignOut={signOut} />}>
        <Route path="/daily/scan" element={<DailyScan onExpired={expired} />} />
        <Route path="/daily/review" element={<DailyReview onExpired={expired} />} />
        <Route path="/daily/payouts" element={<Payouts onExpired={expired} />} />
        <Route path="/daily/summary" element={<DailySummary onExpired={expired} />} />
        <Route path="/daily/history" element={<DailyHistory admin={admin} onExpired={expired} />} />
        <Route path="/masters" element={<Masters onExpired={expired} />} />
        {admin && (
          <>
            <Route path="/monthly/generate" element={<Generate onExpired={expired} />} />
            <Route path="/monthly/review" element={<ScanReview onExpired={expired} />} />
            <Route path="/monthly/inputs" element={<MonthlyInputs onExpired={expired} />} />
            <Route path="/monthly/history" element={<History onExpired={expired} />} />
            <Route path="/admin/audit" element={<AuditLog onExpired={expired} />} />
            <Route path="/admin/users" element={<Users me={user} onExpired={expired} />} />
          </>
        )}
        <Route path="*" element={<Navigate to="/daily/payouts" replace />} />
      </Route>
    </Routes>
  );
}
