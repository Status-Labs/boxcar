#!/usr/bin/env python3
"""Self-contained read->extract->act scenario.

Runs on the HOST (127.0.0.1:PORT); the VM reaches it at http://10.0.2.2:PORT.
Shows a read-only invoices table plus a single "send a reminder to [name]" form.
The agent must READ the table, EXTRACT the customer whose status is "Overdue",
and ACT by typing that name and clicking Send. The typed name is recorded to
reminders.json so we can verify the agent extracted the right customer.

This isolates the cognition (which customer is overdue?) from brittle row-aligned
clicking: GPT-5 reads/reasons correctly but mis-grounds *which row's* button to
click in a dense table (it anchors on the first row), so per-row action buttons
fail; a single field + button is reliably groundable.

Exactly one row is Overdue: Globex Inc.

    python3 server.py [port]      # default 8002
"""
import http.server
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "reminders.json")
ROWS = [
    {"id": 1, "customer": "Acme Corp",    "amount": "$1,200.00", "status": "Paid"},
    {"id": 2, "customer": "Globex Inc",   "amount": "$890.00",   "status": "Overdue"},
    {"id": 3, "customer": "Initech",      "amount": "$450.00",   "status": "Pending"},
    {"id": 4, "customer": "Umbrella LLC", "amount": "$2,300.00", "status": "Paid"},
    {"id": 5, "customer": "Soylent Co",   "amount": "$1,750.00", "status": "Pending"},
]
BADGE = {"Paid": "#127a4b", "Overdue": "#c62828", "Pending": "#8a6d00"}

CSS = """
body{font-family:Arial,Helvetica,sans-serif;background:#eef2f7;margin:0;color:#15243a}
.bar{background:#2a3f5f;color:#fff;padding:14px 22px;font-size:20px;font-weight:bold}
.box{max-width:760px;margin:16px auto;background:#fff;border-radius:10px;
padding:20px;box-shadow:0 2px 12px rgba(0,0,0,.12)}
table{width:100%;border-collapse:collapse;font-size:17px}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid #e3e8f0}
tr:nth-child(even) td{background:#f6f8fb}
th{color:#5a6b85;font-size:13px;text-transform:uppercase;letter-spacing:.04em;padding:14px}
.badge{color:#fff;padding:6px 16px;border-radius:14px;font-size:15px;font-weight:bold}
button{background:#2a3f5f;color:#fff;border:0;padding:14px 28px;font-size:17px;
border-radius:6px;cursor:pointer}
a{text-decoration:none}
label{display:block;margin:22px 0 8px;font-weight:bold;font-size:17px}
input{width:100%;padding:14px;font-size:17px;border:1px solid #b6c2d4;
border-radius:6px;box-sizing:border-box}
.form{margin-top:14px;border-top:2px solid #e3e8f0;padding-top:8px}
"""


def render(title, body):
    return ("<!doctype html><html><head><meta charset=utf-8><title>" + title
            + "</title><style>" + CSS + "</style></head><body>"
            "<div class=bar>&#129534; Acct Receivable</div><div class=box>" + body
            + "</div></body></html>")


def table_page():
    rows = ""
    for r in ROWS:
        badge = (f'<span class=badge style="background:{BADGE[r["status"]]}">'
                 f'{r["status"]}</span>')
        rows += (f"<tr><td>{r['customer']}</td><td>{r['amount']}</td>"
                 f"<td>{badge}</td></tr>")
    return render("Invoices",
                  "<h2>Open Invoices</h2><table>"
                  "<tr><th>Customer</th><th>Amount</th><th>Status</th></tr>"
                  + rows + "</table>"
                  "<div class=form><form method=post action=/send>"
                  "<label>Send a reminder to (type the customer name):</label>"
                  "<input name=customer autocomplete=off>"
                  "<button type=submit>Send reminder</button></form></div>")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, html, code=200):
        b = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        return self._send(table_page())

    def do_POST(self):
        if self.path != "/send":
            return self._send(render("?", "Not found"), 404)
        n = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        name = (form.get("customer", [""])[0]).strip()
        log = json.load(open(LOG)) if os.path.exists(LOG) else []
        log.append({"customer": name})
        json.dump(log, open(LOG, "w"), indent=2)
        return self._send(render(
            "Sent",
            f"<h2>Reminder sent to {name or '(blank)'} &#10003;</h2>"
            "<a href=/><button>Back</button></a>"))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8002
    if os.path.exists(LOG):
        os.remove(LOG)
    print(f"invoices server on http://127.0.0.1:{port}  (guest: http://10.0.2.2:{port})")
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
