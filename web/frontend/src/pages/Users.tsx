/*
 * Users.tsx - Who may sign in (admin only)
 * ========================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * The list of people allowed into the tool, found by the e-mail address
 * of their Google account, each as:
 *      Admin   sees everything
 *      Staff   sees the daily payouts only
 *
 * An admin can add a person, change a role, make someone inactive (they
 * stay in the list but can no longer sign in) and remove someone.
 *
 * RULES (kept by the server - app/data/users_repo.py - not by this screen)
 *   * an e-mail address appears once;
 *   * the last active admin cannot be removed, made inactive or made
 *     staff. The server refuses and its sentence is shown above the table;
 *   * every change is written to the audit log with the e-mail of the
 *     admin who made it.
 *
 * Removing asks for confirmation in the row itself (Remove -> "Remove?
 * Yes / No"), because it cannot be undone from the screen.
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, Role, User, api, showDateTime } from "../api";

interface Props {
  me: User;
  onExpired: () => void;
}

export default function Users({ me, onExpired }: Props) {
  const [users, setUsers] = useState<User[] | null>(null);
  const [problem, setProblem] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("staff");
  const [asking, setAsking] = useState<number | null>(null);   // row asking "Remove?"

  /** Run a request; show the server's sentence if it refuses; then re-read the list. */
  const run = useCallback(async (action: () => Promise<unknown>) => {
    setProblem("");
    try {
      await action();
      setUsers(await api.users());
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
      return false;
    }
  }, [onExpired]);

  useEffect(() => {
    void run(async () => undefined);
  }, [run]);

  const add = async (event: FormEvent) => {
    event.preventDefault();
    if (await run(() => api.addUser(email, name, role))) {
      setEmail("");
      setName("");
      setRole("staff");
    }
  };

  return (
    <>
      <h1>Users</h1>
      <p className="muted">Only the people listed here can sign in. Admins see everything;
        staff see the daily payouts only.</p>

      <form className="card add-user" onSubmit={add}>
        <label>E-mail (Google account)
          <input type="email" required value={email} placeholder="name@gmail.com"
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>Role
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="staff">Staff</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <button className="btn primary">Add user</button>
      </form>

      {problem && <div className="error" role="alert">{problem}</div>}

      <div className="card table-card">
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>E-mail</th><th>Name</th><th>Role</th><th>Status</th>
                  <th>Last sign-in</th><th /></tr>
            </thead>
            <tbody>
              {users === null && <tr><td colSpan={6} className="muted">Reading…</td></tr>}
              {users?.map((u) => (
                <tr key={u.id} className={u.active ? "" : "inactive"}>
                  <td>{u.email}{u.id === me.id && <span className="badge blue">You</span>}</td>
                  <td>{u.name}</td>
                  <td>
                    <select value={u.role} aria-label={`Role of ${u.email}`}
                            onChange={(e) => void run(() => api.changeUser(u.id, { role: e.target.value as Role }))}>
                      <option value="staff">Staff</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td><span className={u.active ? "badge green" : "badge grey"}>
                    {u.active ? "Active" : "Inactive"}</span></td>
                  <td>{showDateTime(u.last_login) || <span className="muted">Never</span>}</td>
                  <td className="row-actions">
                    {asking === u.id ? (
                      <>
                        <span>Remove?</span>
                        <button className="btn danger" onClick={() => {
                          setAsking(null);
                          void run(() => api.removeUser(u.id));
                        }}>Yes</button>
                        <button className="btn" onClick={() => setAsking(null)}>No</button>
                      </>
                    ) : (
                      <>
                        <button className="btn" onClick={() => void run(() => api.changeUser(u.id, { active: !u.active }))}>
                          {u.active ? "Make inactive" : "Make active"}
                        </button>
                        <button className="btn" onClick={() => setAsking(u.id)}>Remove</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
