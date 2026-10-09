"""
security.py - Sign-in: checking Google's answer and the sign-in cookie (v0.23.0)
================================================================================

WHAT THIS MODULE DOES
---------------------
HOW A PERSON SIGNS IN
    1. They press "Sign in with Google" on the sign-in page. Google asks
       for their password (the tool never sees it) and hands the page a
       signed note saying "this is asha@gmail.com" - the "credential".
    2. The page sends that note to the server. `verify_google` checks that
       the note really is from Google, was made for THIS tool (the client
       ID) and that the address is verified.
    3. The server looks the address up in the users list. Not in the list,
       or inactive: refused.
    4. The server gives the browser a COOKIE - a small signed ticket holding
       only the user's number in the list. The browser shows it with every
       later request, so the person stays signed in.

THE COOKIE
    * signed with the server's secret key (`Sessions`): a ticket that was
      altered or made up by someone else does not verify;
    * valid for a limited time (12 hours by default), then the person signs
      in again;
    * "HttpOnly": scripts on the page cannot read it; "SameSite=Lax" and,
      on the real server, "Secure" (HTTPS only);
    * it holds no role. The role is read from the users list at EVERY
      request, so making someone inactive takes effect at once.

No database code here.
"""

from __future__ import annotations

from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE = "dns_session"


class SignInError(Exception):
    """A plain-language reason a sign-in was refused."""


class Sessions:
    """Makes and checks the signed sign-in ticket kept in the cookie."""

    def __init__(self, secret: str, hours: float):
        self._signer = URLSafeTimedSerializer(secret, salt="dns-web-session")
        self.max_age = int(hours * 3600)

    def make(self, user_id: int) -> str:
        return self._signer.dumps({"uid": int(user_id)})

    def read(self, ticket: str | None) -> int | None:
        """The user's number, or None when the ticket is missing, altered or expired."""
        if not ticket:
            return None
        try:
            return int(self._signer.loads(ticket, max_age=self.max_age)["uid"])
        except (BadSignature, KeyError, TypeError, ValueError):
            return None


def verify_google(credential: str, client_id: str) -> dict:
    """
    Check Google's signed note and return {"email", "name"}.
    Raises SignInError when it is not genuine, not meant for this tool, or
    the address is not verified by Google.
    """
    if not client_id:
        raise SignInError("Google sign-in is not set up on this server yet.")
    # Imported here so the rest of the server (and its tests) also start on
    # a PC where Google's package is not installed.
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    try:
        claims = id_token.verify_oauth2_token(credential, google_requests.Request(),
                                              client_id)
    except Exception as exc:                 # wrong signature, expired, other tool ...
        raise SignInError("Google could not confirm this sign-in. Please try "
                          "again.") from exc
    if not claims.get("email") or not claims.get("email_verified"):
        raise SignInError("This Google account has no verified e-mail address.")
    return {"email": claims["email"], "name": claims.get("name", "")}
