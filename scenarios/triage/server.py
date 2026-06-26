#!/usr/bin/env python3
"""Self-contained mock issue tracker for a read -> reason -> act triage flow.

The page lists three support tickets. Exactly one describes a **production
outage** (critical) and should be triaged **High**; the others are clearly minor.
The agent must read the tickets, decide which is critical, then in the single
triage form pick that ticket's ID and set Priority = High via a <select> dropdown,
and Submit. The submission is appended to triage.json (git-ignored) for scoring.

This adds two things the other web scenarios don't: reasoning over several items
to pick the right one, and operating a real <select> dropdown.

Runs on the HOST; the guest reaches it at http://10.0.2.2:PORT.

    python3 server.py [port]      # default 8004
"""
import http.server
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "triage.json")

# id 102 is the critical one (production outage / data-loss). The others are minor.
TICKETS = [
    {"id": "101", "title": "Typo on the pricing page",
     "body": "The word 'recieve' is misspelled in the footer of /pricing."},
    {"id": "102", "title": "Production API is down for all customers",
     "body": "Since 09:15 every request to api.acme.example returns 503. No customer "
             "can log in or load data. Total outage."},
    {"id": "103", "title": "Add a dark-mode toggle (nice to have)",
     "body": "It would be nice to have a dark theme some day. Low urgency."},
]
CRITICAL_ID = "102"
TICKET_IDS = [t["id"] for t in TICKETS]

CSS = """
body{font-family:Arial,Helvetica,sans-serif;background:#eef2f7;margin:0;color:#15243a}
.bar{background:#0b7285;color:#fff;padding:14px 22px;font-size:20px;font-weight:bold}
.box{max-width:720px;margin:28px auto;background:#fff;border-radius:10px;
padding:26px;box-shadow:0 2px 12px rgba(0,0,0,.12)}
.tk{border:1px solid #dde3ec;border-radius:8px;padding:14px 16px;margin:12px 0}
.tk .id{color:#7a8aa0;font-size:13px}.tk .t{font-weight:bold;font-size:17px;margin:3px 0}
label{display:block;margin:16px 0 6px;font-weight:bold}
select,input{padding:11px;font-size:16px;border:1px solid #b6c2d4;border-radius:6px}
button{margin-top:20px;background:#0b7285;color:#fff;border:0;padding:13px 26px;
font-size:17px;border-radius:6px;cursor:pointer}
"""


def render(title, body):
    return ("<!doctype html><html><head><meta charset=utf-8><title>" + title
            + "</title><style>" + CSS + "</style></head><body>"
            "<div class=bar>&#127915; DemoTracker</div><div class=box>" + body
            + "</div></body></html>")


def tickets_html():
    out = []
    for t in TICKETS:
        out.append(f"<div class=tk><div class=id>#{t['id']}</div>"
                   f"<div class=t>{t['title']}</div><div>{t['body']}</div></div>")
    return "".join(out)


def form_html():
    ids = "".join(f"<option value={i}>#{i}</option>" for i in TICKET_IDS)
    prios = "".join(f"<option value={p}>{p}</option>"
                    for p in ("", "Low", "Medium", "High"))
    return ("<h3>Triage a ticket</h3><form method=post action=/triage>"
            f"<label>Ticket</label><select name=ticket>{ids}</select>"
            f"<label>Priority</label><select name=priority>{prios}</select><br>"
            "<button type=submit>Submit triage</button></form>")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, html, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/tickets"):
            return self._send(render(
                "Tickets", "<h2>Open tickets</h2>" + tickets_html() + form_html()))
        if path == "/triage.json":
            data = json.load(open(LOG)) if os.path.exists(LOG) else []
            return self._send(render(
                "Triage log", "<pre>" + json.dumps(data, indent=2) + "</pre>"))
        return self._send(render("404", "Not found"), 404)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/triage":
            return self._send(render("404", "Not found"), 404)
        n = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in
                urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}
        recs = json.load(open(LOG)) if os.path.exists(LOG) else []
        recs.append({"ticket": form.get("ticket", ""), "priority": form.get("priority", "")})
        json.dump(recs, open(LOG, "w"), indent=2)
        return self._send(render(
            "Saved",
            f"<h2>Triage recorded &#10003;</h2><p>Ticket #{form.get('ticket', '')} "
            f"set to <b>{form.get('priority', '')}</b>.</p>"
            "<a href=/><button>Back to tickets</button></a>"))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8004
    if os.path.exists(LOG):
        os.remove(LOG)
    print(f"mock tracker on http://127.0.0.1:{port}  (guest: http://10.0.2.2:{port})")
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
