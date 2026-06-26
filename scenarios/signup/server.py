#!/usr/bin/env python3
"""Self-contained mock multi-page sign-up wizard.

A genuinely multi-step **web app** flow: three pages the agent must navigate in
order — Account -> Profile -> Review -> Create. State is carried between pages in
hidden form fields (no DB, no cookies), so the flow is fully stateless until the
final POST appends the new account to accounts.json (git-ignored), which the
scenario reads back to verify.

Runs on the HOST (127.0.0.1:PORT); the VM's browser reaches it at
http://10.0.2.2:PORT (QEMU user-net gateway -> host loopback).

    python3 server.py [port]      # default 8003
"""
import http.server
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS = os.path.join(HERE, "accounts.json")

# The fields collected across the wizard. (name, label, page, type)
ACCOUNT_FIELDS = ["username", "email", "password"]
PROFILE_FIELDS = ["full_name", "company", "role"]
ALL_FIELDS = ACCOUNT_FIELDS + PROFILE_FIELDS

CSS = """
body{font-family:Arial,Helvetica,sans-serif;background:#eef2f7;margin:0;color:#15243a}
.bar{background:#5b3fd6;color:#fff;padding:14px 22px;font-size:20px;font-weight:bold}
.box{max-width:560px;margin:32px auto;background:#fff;border-radius:10px;
padding:28px;box-shadow:0 2px 12px rgba(0,0,0,.12)}
label{display:block;margin:16px 0 6px;font-weight:bold}
input{width:100%;padding:12px;font-size:16px;border:1px solid #b6c2d4;
border-radius:6px;box-sizing:border-box}
button{margin-top:22px;background:#5b3fd6;color:#fff;border:0;padding:14px 28px;
font-size:17px;border-radius:6px;cursor:pointer}
.steps{color:#6a7790;font-size:14px;margin-bottom:6px}
.rev{background:#f6f8fb;padding:16px;border-radius:6px}
.rev div{margin:6px 0}
.chk{display:flex;align-items:center;gap:12px;margin-top:18px;padding:14px 16px;
border:1px solid #cdd6e4;border-radius:8px;cursor:pointer;font-size:17px;font-weight:bold}
.chk input{width:24px;height:24px;flex:none}
"""


def render(title, body):
    return ("<!doctype html><html><head><meta charset=utf-8><title>" + title
            + "</title><style>" + CSS + "</style></head><body>"
            "<div class=bar>&#128273; DemoSignup</div><div class=box>" + body
            + "</div></body></html>")


def hidden(data, only):
    return "".join(f'<input type=hidden name={k} value="{esc(data.get(k, ""))}">'
                   for k in only)


def esc(s):
    return (s or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def field(name, label, value="", typ="text", autofocus=False):
    # Autofocus the first field of each step so the agent (and a human) can type
    # immediately — no miss-prone click needed to focus it.
    af = " autofocus" if autofocus else ""
    return (f'<label>{label}</label>'
            f'<input name={name} type={typ} value="{esc(value)}" autocomplete=off{af}>')


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, html, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _form(self):
        n = int(self.headers.get("Content-Length", 0))
        return {k: v[0] for k, v in
                urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}

    # ---- page 1: account ----------------------------------------------------
    def _page_account(self, d=None):
        d = d or {}
        return self._send(render(
            "Step 1 — Account",
            "<div class=steps>Step 1 of 3 — Account</div><h2>Create your account</h2>"
            "<form method=post action=/profile>"
            + field("username", "Username", d.get("username", ""), autofocus=True)
            + field("email", "Email", d.get("email", ""))
            + field("password", "Password", d.get("password", ""), "password")
            + "<button type=submit>Next: Profile</button></form>"))

    # ---- page 2: profile ----------------------------------------------------
    def _page_profile(self, d):
        return self._send(render(
            "Step 2 — Profile",
            "<div class=steps>Step 2 of 3 — Profile</div><h2>Tell us about you</h2>"
            "<form method=post action=/review>"
            + hidden(d, ACCOUNT_FIELDS)
            + field("full_name", "Full name", d.get("full_name", ""), autofocus=True)
            + field("company", "Company", d.get("company", ""))
            + field("role", "Role", d.get("role", ""))
            + "<button type=submit>Next: Review</button></form>"))

    # ---- page 3: review + submit -------------------------------------------
    def _page_review(self, d):
        rows = "".join(f"<div><b>{f.replace('_', ' ').title()}:</b> "
                       f"{esc(d.get(f, '')) if f != 'password' else '••••••'}</div>"
                       for f in ALL_FIELDS)
        return self._send(render(
            "Step 3 — Review",
            "<div class=steps>Step 3 of 3 — Review &amp; confirm</div>"
            "<h2>Review your details</h2>"
            f"<div class=rev>{rows}</div>"
            "<form method=post action=/create>"
            + hidden(d, ALL_FIELDS)
            # Whole row is the <label>, so a click anywhere on it toggles the box —
            # a large, unambiguous target instead of a tiny checkbox.
            + "<label class=chk><input type=checkbox name=agree value=yes> "
              "I agree to the terms of service</label>"
            "<button type=submit>Create account</button></form>"))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/signup"):
            return self._page_account()
        if path == "/accounts":  # for manual verification
            data = json.load(open(ACCOUNTS)) if os.path.exists(ACCOUNTS) else []
            return self._send(render(
                "Accounts",
                "<h2>Created accounts</h2><pre>" + json.dumps(data, indent=2) + "</pre>"))
        return self._send(render("404", "Not found"), 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        d = self._form()
        if path == "/profile":
            return self._page_profile(d)
        if path == "/review":
            return self._page_review(d)
        if path == "/create":
            if d.get("agree") != "yes":
                return self._send(render(
                    "Terms required",
                    "<h2>Please accept the terms</h2><p>You must tick "
                    "&ldquo;I agree to the terms of service&rdquo; to continue.</p>"
                    "<a href=javascript:history.back()><button>Go back</button></a>"))
            record = {f: d.get(f, "") for f in ALL_FIELDS}
            record["agree"] = True
            accounts = json.load(open(ACCOUNTS)) if os.path.exists(ACCOUNTS) else []
            accounts.append(record)
            json.dump(accounts, open(ACCOUNTS, "w"), indent=2)
            return self._send(render(
                "Welcome",
                f"<h2>Account created &#10003;</h2><p>Welcome, "
                f"{esc(record['full_name']) or esc(record['username'])}!</p>"))
        return self._send(render("404", "Not found"), 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8003
    if os.path.exists(ACCOUNTS):
        os.remove(ACCOUNTS)
    print(f"mock signup on http://127.0.0.1:{port}  (guest: http://10.0.2.2:{port})")
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
