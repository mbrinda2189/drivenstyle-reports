/*
 * Shell.tsx - The frame around every screen
 * =========================================
 *
 * WHAT THIS FILE DOES
 * -------------------
 * Draws what stays the same on every screen (layout approved by Brinda on
 * the mockup, 09-10-2026):
 *
 *   +----------------------------------------------------------------+
 *   | Drive N Style   [ Daily payouts | Monthly reports ]   who  Out |   top bar
 *   +-----------+----------------------------------------------------+
 *   | DAILY     |                                                    |
 *   |  Scan     |              the screen itself                     |
 *   |  Review   |              (<Outlet />)                          |
 *   |  Payouts  |                                                    |
 *   |  History  |                                                    |
 *   | SHARED    |                                                    |
 *   |  Masters  |                                                    |
 *   | ADMIN     |   (admins only)                                    |
 *   |  Audit log, Users                                              |
 *   +-----------+----------------------------------------------------+
 *
 * WHICH TAB IS "ON"
 *   The address decides: /daily/... = Daily, /monthly/... = Monthly.
 *   The shared screens (/masters, /admin/...) belong to both, so there the tab the
 *   person was on last stays on - going to Masters from Monthly reports
 *   does not throw them over to Daily.
 *
 * ROLES
 *   Staff see the Daily payouts menu and Masters (Brinda, 09-10-2026:
 *   staff enter cost prices and rates): no tab bar - one tab needs no bar.
 *   Audit log and Users are for admins only.
 */
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { User } from "./api";

type Tab = "daily" | "monthly";

const MENU: Record<Tab, { heading: string; items: [string, string][] }> = {
  daily: {
    heading: "Daily payouts",
    items: [["/daily/scan", "Scan invoices"], ["/daily/review", "Review"],
            ["/daily/payouts", "Payouts"], ["/daily/history", "History"]],
  },
  monthly: {
    heading: "Monthly reports",
    items: [["/monthly/generate", "Generate reports"], ["/monthly/review", "Scan review"],
            ["/monthly/inputs", "Monthly inputs"], ["/monthly/history", "History"]],
  },
};
/** Used by both tools, so listed under both tabs. Open to staff as well. */
const SHARED: [string, string][] = [["/masters", "Masters"]];
const ADMIN_ONLY: [string, string][] = [["/admin/audit", "Audit log"], ["/admin/users", "Users"]];
/** The screen each tab opens on. */
const HOME: Record<Tab, string> = { daily: "/daily/payouts", monthly: "/monthly/generate" };

interface Props {
  user: User;
  version: string;
  onSignOut: () => void;
}

export default function Shell({ user, version, onSignOut }: Props) {
  const admin = user.role === "admin";
  const { pathname } = useLocation();
  const [tab, setTab] = useState<Tab>(pathname.startsWith("/monthly") && admin ? "monthly" : "daily");

  // Follow the address (Back / Forward, a typed address); /admin keeps the tab.
  useEffect(() => {
    if (pathname.startsWith("/daily")) setTab("daily");
    else if (pathname.startsWith("/monthly") && admin) setTab("monthly");
  }, [pathname, admin]);

  const menu = MENU[tab];
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-name">Drive N Style</div>
          <div className="brand-sub">Reports and payouts</div>
        </div>
        {admin && (
          <nav className="tabs" aria-label="Main sections">
            {(Object.keys(MENU) as Tab[]).map((key) => (
              <NavLink key={key} to={HOME[key]} onClick={() => setTab(key)}
                       className={tab === key ? "tab on" : "tab"}
                       aria-current={tab === key ? "page" : undefined}>
                {MENU[key].heading}
              </NavLink>
            ))}
          </nav>
        )}
        <div className="spacer" />
        <div className="who">
          <div className="who-email">{user.email}</div>
          <div className="who-role">{admin ? "Admin" : "Staff"}</div>
        </div>
        <button className="btn on-dark" onClick={onSignOut}>Sign out</button>
      </header>

      <div className="body">
        <nav className="side" aria-label={menu.heading}>
          <div className="side-heading">{menu.heading}</div>
          {menu.items.map(([to, label]) => (
            <NavLink key={to} to={to} className="side-link">{label}</NavLink>
          ))}
          <div className="side-heading gap">Shared</div>
          {SHARED.map(([to, label]) => (
            <NavLink key={to} to={to} className="side-link">{label}</NavLink>
          ))}
          {admin && (
            <>
              <div className="side-heading gap">Admin</div>
              {ADMIN_ONLY.map(([to, label]) => (
                <NavLink key={to} to={to} className="side-link">{label}</NavLink>
              ))}
            </>
          )}
          <div className="side-version">v{version}</div>
        </nav>
        <main className="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
