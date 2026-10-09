/*
 * SignIn.tsx - The sign-in page
 * =============================
 *
 * WHAT THIS FILE DOES
 * -------------------
 * Shown whenever nobody is signed in.
 *
 * GOOGLE SIGN-IN
 *   Google's own script draws the "Sign in with Google" button and asks
 *   for the password in Google's window - this tool never sees a password.
 *   Google then hands back a signed note (the "credential"), which is sent
 *   to the server; the server checks it and looks the e-mail address up in
 *   the users list (web/backend/security.py). Not on the list: the
 *   server's sentence is shown here.
 *   The button needs the server's Google client ID. Until that is set up,
 *   the page says so instead of showing a button that cannot work.
 *
 * TEST SIGN-IN (only on a developer's PC)
 *   When the server runs with DNS_WEB_DEV_LOGIN=1 a second box appears:
 *   type an e-mail address of the users list to enter without Google. It
 *   is marked in amber so it can never be mistaken for the real thing.
 */
import { FormEvent, useEffect, useRef, useState } from "react";
import { Config, User, api } from "../api";

// The small part of Google's script this page uses.
interface GoogleAccounts {
  id: {
    initialize(options: { client_id: string; callback: (r: { credential: string }) => void }): void;
    renderButton(parent: HTMLElement, options: Record<string, string | number>): void;
  };
}
declare global {
  interface Window {
    google?: { accounts: GoogleAccounts };
  }
}

const GOOGLE_SCRIPT = "https://accounts.google.com/gsi/client";

interface Props {
  config: Config;
  onSignedIn: (user: User) => void;
}

export default function SignIn({ config, onSignedIn }: Props) {
  const [problem, setProblem] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const googleBox = useRef<HTMLDivElement>(null);

  const finish = async (signIn: () => Promise<User>) => {
    setBusy(true);
    setProblem("");
    try {
      onSignedIn(await signIn());
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  // Load Google's script once and let it draw its button.
  useEffect(() => {
    if (!config.google_client_id) return;
    const draw = () => {
      if (!window.google || !googleBox.current) return;
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: (reply) => void finish(() => api.signInGoogle(reply.credential)),
      });
      window.google.accounts.id.renderButton(googleBox.current,
        { theme: "filled_blue", size: "large", text: "signin_with", width: 300 });
    };
    if (window.google) {
      draw();
      return;
    }
    const script = document.createElement("script");
    script.src = GOOGLE_SCRIPT;
    script.async = true;
    script.onload = draw;
    script.onerror = () => setProblem("Google's sign-in could not be loaded. If this "
      + "PC blocks accounts.google.com, ask IT to allow it.");
    document.head.appendChild(script);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.google_client_id]);

  const testSignIn = (event: FormEvent) => {
    event.preventDefault();
    void finish(() => api.signInTest(email));
  };

  return (
    <div className="signin">
      <div className="signin-card">
        <div className="signin-brand">Drive N Style</div>
        <div className="signin-sub">Reports and payouts</div>
        <h1>Sign in</h1>
        <p className="muted">Use the Google account an admin has added to this tool.</p>

        {config.google_client_id
          ? <div ref={googleBox} className="google-box" />
          : <div className="note">Google sign-in is not set up on this server yet.</div>}

        {problem && <div className="error" role="alert">{problem}</div>}

        {config.dev_login && (
          <form className="test-signin" onSubmit={testSignIn}>
            <div className="test-label">Test sign-in is ON – developer's PC only</div>
            <label htmlFor="test-email">E-mail address on the users list</label>
            <input id="test-email" type="email" required value={email}
                   onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" />
            <button className="btn primary" disabled={busy}>Sign in (test)</button>
          </form>
        )}
        <div className="signin-version">v{config.version}</div>
      </div>
    </div>
  );
}
