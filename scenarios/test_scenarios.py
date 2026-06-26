#!/usr/bin/env python3
"""Host-only tests for the web scenarios — no VM required.

For each web scenario we start its server in-process (exactly as the eval runner
does), drive the HTTP flow a successful agent would produce, and assert that
`check()` returns pass. We also assert `check()` *fails* on the untouched initial
state — so a scenario can never score a false positive. This validates the
scoring logic and the servers; the agent/VM half is covered by a live eval run.

    cd <repo root>
    control/.venv/bin/python -m scenarios.test_scenarios
"""
import sys
import urllib.error
import urllib.parse
import urllib.request

from .framework import ScenarioContext
from .registry import get


def _post(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, body, headers=headers or {})
    return urllib.request.urlopen(req).read().decode()


def _get(url):
    return urllib.request.urlopen(url).read().decode()


def _run(scenario, drive):
    """setup -> (check fails on empty) -> drive the flow -> (check passes)."""
    ctx = ScenarioContext(port=0)
    scenario.setup(ctx, vm=None)
    try:
        pre = scenario.check(ctx, vm=None)
        assert not pre.passed, f"{scenario.name}: check passed on empty state ({pre.detail})"
        drive(ctx)
        post = scenario.check(ctx, vm=None)
        assert post.passed, f"{scenario.name}: check failed after a good run ({post.detail})"
        assert post.score >= 0.99, f"{scenario.name}: expected full score, got {post.score}"
        print(f"  ok  {scenario.name:9} pre=fail post=pass  — {post.detail}")
    finally:
        if scenario.teardown:
            scenario.teardown(ctx, vm=None)
        ctx.stop()


def test_webmail():
    def drive(ctx):
        # /draft requires the signed-in cookie the login flow would set.
        _post(ctx.host_url("/draft"),
              {"to": "Dana", "subject": "Re: Lunch",
               "body": "Yes! Lunch Tuesday at noon works great."},
              headers={"Cookie": "sid=ok"})
    _run(get("webmail"), drive)


def test_invoices():
    def drive(ctx):
        _post(ctx.host_url("/send"), {"customer": "Globex Inc"})
    _run(get("invoices"), drive)


def test_signup():
    def drive(ctx):
        base = ctx.host_url()
        # Mirror the wizard: each POST carries forward the prior fields.
        acct = {"username": "jdoe", "email": "jdoe@acme.example", "password": "Hunter2!"}
        prof = dict(acct, full_name="Jane Doe", company="Acme", role="Engineer")
        _post(base + "profile", acct)
        _post(base + "review", prof)
        _post(base + "create", dict(prof, agree="yes"))
    _run(get("signup"), drive)


def test_triage():
    def drive(ctx):
        _post(ctx.host_url("/triage"), {"ticket": "102", "priority": "High"})
    _run(get("triage"), drive)


def test_expense():
    def drive(ctx):
        _post(ctx.host_url("/report"), {"category": "Travel", "amount": "312.50"})
    _run(get("expense"), drive)


def test_download_routing():
    """The CSV must be served at BOTH /download and /sales.csv, and unknown paths
    must 404 — not silently return the HTML page (which an agent would save as
    sales.csv and parse to a bogus total)."""
    sc = get("download")
    ctx = ScenarioContext(port=0)
    sc.setup(ctx, vm=None)
    try:
        for path in ("/download", "/sales.csv"):
            body = _get(ctx.host_url(path))
            assert "amount" in body and "120.50" in body, f"{path} did not serve the CSV"
        try:
            _get(ctx.host_url("/sales.cvs"))  # typo'd path
            raise AssertionError("unknown path should 404, not return 200")
        except urllib.error.HTTPError as e:
            assert e.code == 404, f"expected 404 for unknown path, got {e.code}"
        print("  ok  download  CSV at /download + /sales.csv, unknown path 404s")
    finally:
        if sc.teardown:
            sc.teardown(ctx, vm=None)
        ctx.stop()


def test_signup_partial_scores_below_one():
    """A wrong field should yield partial (<1.0) credit, not a pass at full score."""
    sc = get("signup")
    ctx = ScenarioContext(port=0)
    sc.setup(ctx, vm=None)
    try:
        base = ctx.host_url()
        bad = {"username": "jdoe", "email": "WRONG@x", "password": "Hunter2!",
               "full_name": "Jane Doe", "company": "Acme", "role": "Engineer"}
        _post(base + "create", dict(bad, agree="yes"))
        r = sc.check(ctx, vm=None)
        assert 0 < r.score < 1.0, f"expected partial score, got {r.score} ({r.detail})"
        print(f"  ok  signup    partial credit works — score={r.score:.2f} ({r.detail})")
    finally:
        ctx.stop()


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} host-only scenario tests...")
    for t in tests:
        t()
    print(f"\nall {len(tests)} passed.")


if __name__ == "__main__":
    sys.exit(main())
