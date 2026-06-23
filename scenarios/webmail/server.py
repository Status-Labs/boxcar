#!/usr/bin/env python3
"""Self-contained mock webmail for the "log in + draft an email reply" demo.

Runs on the HOST (127.0.0.1:PORT). The VM's browser reaches it at
http://10.0.2.2:PORT (QEMU user-net gateway -> host loopback). No real email and
nothing is ever sent: the agent signs in (demo / demo), reads a seeded message,
clicks Reply, writes a reply, and "Save draft" appends it to drafts.json — which
we read back to verify the flow worked.

    python3 server.py [port]      # default 8000
"""
import http.server
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
DRAFTS = os.path.join(HERE, "drafts.json")
USER, PW = "demo", "demo"
EMAIL = {
    "from": "Dana Whitmore <dana@acme.example>",
    "subject": "Lunch next week?",
    "body": ("Hi!\n\nGreat chatting at the conference. Are you free to grab lunch "
             "sometime next week? I'm open Tuesday or Thursday around noon — let "
             "me know what works for you.\n\nBest,\nDana"),
}

CSS = """
body{font-family:Arial,Helvetica,sans-serif;background:#eef2f7;margin:0;color:#15243a}
.bar{background:#2266dd;color:#fff;padding:14px 22px;font-size:20px;font-weight:bold}
.box{max-width:680px;margin:32px auto;background:#fff;border-radius:10px;
padding:28px;box-shadow:0 2px 12px rgba(0,0,0,.12)}
label{display:block;margin:16px 0 6px;font-weight:bold}
input,textarea{width:100%;padding:12px;font-size:16px;border:1px solid #b6c2d4;
border-radius:6px;box-sizing:border-box}
button{margin-top:20px;background:#2266dd;color:#fff;border:0;padding:14px 28px;
font-size:17px;border-radius:6px;cursor:pointer}
.row{padding:18px;border:1px solid #dde3ec;border-radius:8px;margin-top:14px;cursor:pointer}
.from{font-weight:bold;font-size:17px}.sub{color:#33445e;margin-top:4px}
pre{white-space:pre-wrap;font:inherit;background:#f6f8fb;padding:16px;border-radius:6px}
a{color:inherit;text-decoration:none}
"""


def render(title, body):
    return ("<!doctype html><html><head><meta charset=utf-8><title>" + title
            + "</title><style>" + CSS + "</style></head><body>"
            "<div class=bar>&#128236; DemoMail</div><div class=box>" + body
            + "</div></body></html>")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, html, code=200, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(html.encode())

    def _redirect(self, to, headers=None):
        h = {"Location": to}
        h.update(headers or {})
        self._send("", 302, h)

    def _authed(self):
        return "sid=ok" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/login"):
            if self._authed():
                return self._redirect("/inbox")
            return self._send(render("Sign in",
                "<h2>Sign in to DemoMail</h2>"
                "<form method=post action=/login>"
                "<label>Username</label><input name=username autofocus>"
                "<label>Password</label><input name=password type=password>"
                "<button type=submit>Sign in</button></form>"))
        if not self._authed():
            return self._redirect("/")
        if path == "/inbox":
            return self._send(render("Inbox",
                "<h2>Inbox</h2><a href=/message>"
                f"<div class=row><div class=from>{EMAIL['from']}</div>"
                f"<div class=sub>{EMAIL['subject']}</div></div></a>"))
        if path in ("/message", "/compose"):
            # Email shown with an inline reply box right below (Gmail-style), so
            # replying is: read -> type in the box -> Save draft.
            return self._send(render(EMAIL["subject"],
                f"<h2>{EMAIL['subject']}</h2><p><b>From:</b> {EMAIL['from']}</p>"
                f"<pre>{EMAIL['body']}</pre>"
                "<h3>Reply</h3><form method=post action=/draft>"
                f"<label>To</label><input name=to value=\"{EMAIL['from']}\">"
                f"<label>Subject</label><input name=subject value=\"Re: {EMAIL['subject']}\">"
                "<label>Message</label>"
                "<textarea name=body rows=7 autofocus placeholder=\"Write your reply...\">"
                "</textarea>"
                "<button type=submit>Save draft</button></form>"))
        if path == "/drafts":
            data = json.load(open(DRAFTS)) if os.path.exists(DRAFTS) else []
            return self._send(render("Drafts",
                "<h2>Saved drafts</h2><pre>" + json.dumps(data, indent=2) + "</pre>"))
        return self._send(render("404", "Not found"), 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        def g(k):
            return form.get(k, [""])[0]
        if self.path == "/login":
            if g("username") == USER and g("password") == PW:
                return self._redirect("/inbox", {"Set-Cookie": "sid=ok; Path=/"})
            return self._send(render("Sign in",
                "<p>Invalid login.</p><a href=/>Try again</a>"))
        if self.path == "/draft":
            if not self._authed():
                return self._redirect("/")
            drafts = json.load(open(DRAFTS)) if os.path.exists(DRAFTS) else []
            drafts.append({"to": g("to"), "subject": g("subject"), "body": g("body")})
            json.dump(drafts, open(DRAFTS, "w"), indent=2)
            return self._send(render("Saved",
                "<h2>Draft saved &#10003;</h2>"
                f"<pre>{g('body')}</pre>"
                "<a href=/inbox><button>Back to inbox</button></a>"))
        return self._send(render("404", "Not found"), 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if os.path.exists(DRAFTS):
        os.remove(DRAFTS)
    print(f"mock webmail on http://127.0.0.1:{port}  (guest: http://10.0.2.2:{port})")
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
