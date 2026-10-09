"""
privacy.py - The tool's privacy page (v0.29.0)
==============================================

WHAT THIS MODULE DOES
---------------------
One plain page at  /privacy  that anyone can open WITHOUT signing in. It
says, in ordinary words, what the tool keeps about the people who sign in.

WHY IT EXISTS
    Google asks every app that uses "Sign in with Google" for a home page
    and a privacy page before the app can be PUBLISHED (Google Cloud ->
    Google Auth Platform -> Branding). Until it is published only the
    people listed there as "test users" can sign in. With this page:

        Home page        https://<the tool's address>/
        Privacy policy   https://<the tool's address>/privacy

WHAT THE PAGE SAYS (keep it true when the tool changes)
    * From Google the tool receives a person's name and e-mail address,
      only to check them against its own list of users. No password.
    * It keeps that name, e-mail, the time of the last sign-in, and a log
      of the changes each person makes (the audit log).
    * The business data (invoices, masters, payouts, reports) belongs to
      Drive N Style, stays on their server and is not shared or sold.
    * A cookie keeps a person signed in for some hours; no advertising or
      tracking.

The page is fixed text: no database is read and nothing about the visitor
is recorded. The wording is Brinda's to change (it is a statement by the
firm, not by the program).
"""

from __future__ import annotations

CONTACT = "automation.drivenstyle@gmail.com"

PAGE = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy - Drive N Style Reports</title>
<style>
  body {{ font: 16px/1.6 system-ui, "Segoe UI", Arial, sans-serif; color: #1c2430;
         background: #f5f6f8; margin: 0; padding: 32px 16px; }}
  main {{ max-width: 720px; margin: 0 auto; background: #fff; padding: 32px;
         border: 1px solid #dfe3e8; border-radius: 8px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  h2 {{ font-size: 17px; margin: 28px 0 6px; }}
  p.sub {{ color: #5b6675; margin: 0 0 20px; }}
  a {{ color: #1d4ed8; }}
</style>
</head>
<body>
<main>
<h1>Privacy</h1>
<p class="sub">Drive N Style Reports - the internal tool of Drive N Style, Coimbatore,
for its daily payouts and monthly reports.</p>

<p>This tool is for the staff of Drive N Style and the people who keep its accounts.
It is not open to the public: only people whom an administrator has added can sign in.</p>

<h2>What we receive when you sign in</h2>
<p>You sign in with your Google account. Google tells the tool your <b>name</b> and
<b>e-mail address</b>, and nothing else. The tool never sees your Google password, your
mail, your contacts or your files.</p>

<h2>What the tool keeps about you</h2>
<p>Your name and e-mail address, your role (administrator or staff), the time you last
signed in, and a log of the changes you make in the tool (for example a rate changed or
a payout marked as paid), so that the accounts can be checked later.</p>

<h2>The business data</h2>
<p>Invoices, price lists, payouts and reports entered in the tool belong to Drive N Style.
They are kept on a server used by Drive N Style and are not sold, and are not shared
with anyone outside the firm and its accountants.</p>

<h2>Cookies</h2>
<p>One cookie keeps you signed in for some hours. There is no advertising and no
tracking of what you do elsewhere.</p>

<h2>Removing your details</h2>
<p>An administrator can switch off or remove your sign-in at any time. To ask for
that, or for anything else about this page, write to
<a href="mailto:{CONTACT}">{CONTACT}</a>.</p>
</main>
</body>
</html>
"""
