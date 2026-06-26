#!/usr/bin/env python3
"""Self-contained mock expense dashboard for a read -> compute -> act flow.

The page shows a spend-vs-budget table by category. Exactly one category is over
its monthly budget. The agent must read the table, work out which category is
over and by how much (spent - budget), then fill the report form with that
category name and the overage amount and Submit. The submission is appended to
report.json (git-ignored) for scoring.

This exercises arithmetic reasoning over tabular data, not just transcription.

Runs on the HOST; the guest reaches it at http://10.0.2.2:PORT.

    python3 server.py [port]      # default 8005
"""
import http.server
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "report.json")

# (category, spent, budget). Travel is the only one over budget (+312.50).
ROWS = [
    {"category": "Office", "spent": 420.00, "budget": 600.00},
    {"category": "Travel", "spent": 1812.50, "budget": 1500.00},
    {"category": "Software", "spent": 980.00, "budget": 1000.00},
    {"category": "Meals", "spent": 240.75, "budget": 300.00},
]
OVER = next(r for r in ROWS if r["spent"] > r["budget"])
OVER_CATEGORY = OVER["category"]
OVER_AMOUNT = round(OVER["spent"] - OVER["budget"], 2)   # 312.5

CSS = """
body{font-family:Arial,Helvetica,sans-serif;background:#eef2f7;margin:0;color:#15243a}
.bar{background:#1f7a3d;color:#fff;padding:14px 22px;font-size:20px;font-weight:bold}
.box{max-width:680px;margin:28px auto;background:#fff;border-radius:10px;
padding:26px;box-shadow:0 2px 12px rgba(0,0,0,.12)}
table{border-collapse:collapse;width:100%;margin-top:8px}
th,td{padding:11px 14px;border-bottom:1px solid #e3e8f0;text-align:left}
th{background:#f6f8fb}td.num{text-align:right;font-variant-numeric:tabular-nums}
label{display:block;margin:16px 0 6px;font-weight:bold}
input{width:100%;padding:12px;font-size:16px;border:1px solid #b6c2d4;
border-radius:6px;box-sizing:border-box}
button{margin-top:20px;background:#1f7a3d;color:#fff;border:0;padding:13px 26px;
font-size:17px;border-radius:6px;cursor:pointer}
"""


def render(title, body):
    return ("<!doctype html><html><head><meta charset=utf-8><title>" + title
            + "</title><style>" + CSS + "</style></head><body>"
            "<div class=bar>&#128202; DemoExpenses</div><div class=box>" + body
            + "</div></body></html>")


def table_html():
    head = "<tr><th>Category</th><th>Spent</th><th>Monthly budget</th></tr>"
    body = "".join(
        f"<tr><td>{r['category']}</td>"
        f"<td class=num>${r['spent']:.2f}</td>"
        f"<td class=num>${r['budget']:.2f}</td></tr>" for r in ROWS)
    return f"<table>{head}{body}</table>"


def form_html():
    return ("<h3>Over-budget report</h3>"
            "<p>Enter the category that is over its monthly budget and the overage "
            "amount (spent minus budget).</p>"
            "<form method=post action=/report>"
            "<label>Category over budget</label><input name=category autocomplete=off>"
            "<label>Overage amount (USD)</label><input name=amount autocomplete=off>"
            "<button type=submit>Submit report</button></form>")


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
        if path in ("/", "/dashboard"):
            return self._send(render(
                "Expenses",
                "<h2>This month's spend by category</h2>" + table_html() + form_html()))
        if path == "/report.json":
            data = json.load(open(LOG)) if os.path.exists(LOG) else []
            return self._send(render("Report", "<pre>" + json.dumps(data, indent=2) + "</pre>"))
        return self._send(render("404", "Not found"), 404)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/report":
            return self._send(render("404", "Not found"), 404)
        n = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in
                urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}
        recs = json.load(open(LOG)) if os.path.exists(LOG) else []
        recs.append({"category": form.get("category", ""), "amount": form.get("amount", "")})
        json.dump(recs, open(LOG, "w"), indent=2)
        return self._send(render(
            "Saved",
            "<h2>Report submitted &#10003;</h2>"
            f"<p>{form.get('category', '')}: over by ${form.get('amount', '')}.</p>"
            "<a href=/><button>Back to dashboard</button></a>"))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8005
    if os.path.exists(LOG):
        os.remove(LOG)
    print(f"mock expenses on http://127.0.0.1:{port}  (guest: http://10.0.2.2:{port})")
    print(f"  (over-budget answer: {OVER_CATEGORY} +{OVER_AMOUNT})")
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
