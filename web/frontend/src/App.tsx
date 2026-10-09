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
 * Screens not built yet show a "comes in step N" card, so the whole layout
 * can be seen and clicked through now.
 */
import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { ApiError, Config, User, api } from "./api";
import Shell from "./Shell";
import AuditLog from "./pages/AuditLog";
import ComingSoon from "./pages/ComingSoon";
import Masters from "./pages/Masters";
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
        <Route path="/daily/scan" element={<ComingSoon title="Scan invoices" step={5}
          about="Upload the day's invoice PDFs. Labour and incentive are worked out; an invoice already posted is skipped." />} />
        <Route path="/daily/review" element={<ComingSoon title="Review" step={5}
          about="Anything the scan could not settle: an item, salesperson or vehicle not in the masters." />} />
        <Route path="/daily/payouts" element={<ComingSoon title="Payouts" step={5}
          about="Every labour and incentive line to pay: mark paid with reference and proof, hold, reopen, payout slip." />} />
        <Route path="/daily/history" element={<ComingSoon title="History" step={6}
          about="Payouts of earlier days, the summary, and the check against the monthly reports." />} />
        <Route path="/masters" element={<Masters onExpired={expired} />} />
        {admin && (
          <>
            <Route path="/monthly/generate" element={<ComingSoon title="Generate reports" step={4}
              about="Upload Zoho's invoice export, the payments export and the delivery (RTO) list, then make the workbook and the PDF." />} />
            <Route path="/monthly/review" element={<ComingSoon title="Scan review" step={4}
              about="Items, salespersons and vehicles the month's invoices could not be matched to, each with a fix." />} />
            <Route path="/monthly/inputs" element={<ComingSoon title="Monthly inputs" step={4}
              about="Indirect costs for the month, the high-profit threshold and the automatic cost percentages." />} />
            <Route path="/monthly/history" element={<ComingSoon title="History" step={4}
              about="Months already read and workbooks already made: download, regenerate, remove." />} />
            <Route path="/admin/audit" element={<AuditLog onExpired={expired} />} />
            <Route path="/admin/users" element={<Users me={user} onExpired={expired} />} />
          </>
        )}
        <Route path="*" element={<Navigate to="/daily/payouts" replace />} />
      </Route>
    </Routes>
  );
}
