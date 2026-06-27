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


def _eval_parallel():
    """Import control/eval_parallel (needs control/ on sys.path); skip if absent."""
    import os
    control = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "control")
    if control not in sys.path:
        sys.path.insert(0, control)
    import eval_parallel
    return eval_parallel


def test_parallel_split_round_robin():
    ep = _eval_parallel()
    assert ep.split_round_robin([1, 2, 3, 4, 5], 2) == [[1, 3, 5], [2, 4]]
    assert ep.split_round_robin([1, 2, 3], 3) == [[1], [2], [3]]
    # More buckets than items: trailing empties are dropped, not returned blank.
    assert ep.split_round_robin([1], 4) == [[1]]
    print("  ok  parallel  split_round_robin deals evenly + drops empty buckets")


def test_parallel_parse_clones():
    ep = _eval_parallel()
    ps = (
        "qemu-system-x86_64 -name ubuntu-a -smp 4 -netdev "
        "user,id=net0,hostfwd=tcp:127.0.0.1:2223-:22 -qmp unix:x\n"
        "qemu-system-x86_64 -name ubuntu-bee -netdev "
        "user,id=net0,hostfwd=tcp:127.0.0.1:2224-:22\n"
        "qemu-system-x86_64 -name win11-c -netdev "
        "user,id=net0,hostfwd=tcp:127.0.0.1:2299-:22\n"        # other target: ignored
        "some-other-process --name ubuntu-zzz\n"               # not qemu/no port: ignored
    )
    clones = ep.parse_clones(ps, "ubuntu")
    assert set(clones) == {"a", "bee"}, clones
    assert clones["a"][0] == 2223 and clones["bee"][0] == 2224
    assert clones["a"][1].endswith("vms/ubuntu/clones/a-qmp.sock"), clones["a"][1]
    print("  ok  parallel  parse_clones reads name/port per target, skips others")


def test_parallel_merge_results():
    ep = _eval_parallel()
    shard_a = [{"scenario": "webmail"}, {"scenario": "triage"}]
    shard_b = [{"scenario": "signup"}]
    merged = ep.merge_results([shard_a, shard_b],
                              ["webmail", "signup", "triage", "expense"])
    # Reordered to scenario_order; a scenario no shard reported (expense) is absent.
    assert [r["scenario"] for r in merged] == ["webmail", "signup", "triage"]
    print("  ok  parallel  merge_results restores order + omits unreported")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} host-only scenario tests...")
    for t in tests:
        t()
    print(f"\nall {len(tests)} passed.")


if __name__ == "__main__":
    sys.exit(main())
