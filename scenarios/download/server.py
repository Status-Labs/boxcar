#!/usr/bin/env python3
"""Self-contained cross-app scenario: download a file in the browser, then
process it in the shell.

Runs on the HOST (127.0.0.1:PORT); the VM reaches it at http://10.0.2.2:PORT.
Serves a page with a "Download sales.csv" button; the CSV has a known total so we
can verify the agent's computed answer. Nothing external.

The agent task: download the report, sum the `amount` column with the terminal,
write the total to ~/answer.txt, and report it. Expected total = 976.23.

    python3 server.py [port]      # default 8001
"""
import http.server
import sys

CSV = (
    "date,product,amount\n"
    "2026-01-05,Widget,120.50\n"
    "2026-01-12,Gadget,89.99\n"
    "2026-02-03,Widget,120.50\n"
    "2026-02-20,Gizmo,245.00\n"
    "2026-03-01,Gadget,89.99\n"
    "2026-03-15,Doohickey,310.25\n"
)  # sum(amount) = 976.23

CSS = """
body{font-family:Arial,Helvetica,sans-serif;background:#eef2f7;margin:0;color:#15243a}
.bar{background:#127a4b;color:#fff;padding:14px 22px;font-size:20px;font-weight:bold}
.box{max-width:640px;margin:40px auto;background:#fff;border-radius:10px;
padding:30px;box-shadow:0 2px 12px rgba(0,0,0,.12)}
a.btn button{background:#127a4b;color:#fff;border:0;padding:16px 30px;font-size:18px;
border-radius:8px;cursor:pointer;margin-top:18px}
"""

PAGE = ("<!doctype html><html><head><meta charset=utf-8><title>Acme Reports</title>"
        "<style>" + CSS + "</style></head><body><div class=bar>&#128202; Acme Reports"
        "</div><div class=box><h2>Monthly Sales Report</h2>"
        "<p>Download the latest sales export (CSV) and crunch the numbers.</p>"
        "<a class=btn href=/download><button>Download sales.csv</button></a>"
        "</div></body></html>")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype, headers=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        # Serve the CSV at /download (the button) AND /sales.csv (the obvious
        # guess, matching the filename in the task) so a shell `curl .../sales.csv`
        # gets the real file rather than the HTML page.
        if path in ("/download", "/sales.csv"):
            return self._send(CSV.encode(), "text/csv",
                              {"Content-Disposition": 'attachment; filename="sales.csv"'})
        if path in ("/", "/index.html"):
            return self._send(PAGE.encode(), "text/html; charset=utf-8")
        # 404 unknown paths — don't silently return HTML for a wrong URL, which
        # otherwise gets saved as "sales.csv" and parsed to a bogus 0.0 total.
        body = b"not found\n"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    print(f"download server on http://127.0.0.1:{port}  (guest: http://10.0.2.2:{port})")
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
