"""Scenario spec for the cross-app (browser download -> shell processing) flow.

No host-side state: the verifiable end state lives in the guest filesystem —
~/Downloads/sales.csv must exist and ~/answer.txt must hold the CSV total
(976.23). `check` reads both over SSH.
"""
from ..framework import CheckResult, Scenario, ScenarioContext, guest_path_exists, read_guest_file
from . import server

EXPECTED_TOTAL = 976.23


def setup(ctx: ScenarioContext, vm):
    ctx.serve(server.Handler)


def task(ctx: ScenarioContext) -> str:
    return (f"Open {ctx.guest_url()}, download sales.csv, then with the terminal sum "
            "the 'amount' column of ~/Downloads/sales.csv, write the total to "
            "~/answer.txt, and tell me the total.")


def check(ctx: ScenarioContext, vm) -> CheckResult:
    home = f"/home/{vm.username}"
    have_csv = guest_path_exists(vm, f"{home}/Downloads/sales.csv")
    answer = read_guest_file(vm, f"{home}/answer.txt")
    if answer is None:
        return CheckResult(False, 0.3 if have_csv else 0.0,
                           "~/answer.txt was never written"
                           + (" (but sales.csv downloaded)" if have_csv else ""))
    import re
    m = re.search(r"-?\d+(?:\.\d+)?", answer)
    if not m:
        return CheckResult(False, 0.4, f"answer.txt has no number: {answer.strip()[:40]!r}")
    got = float(m.group())
    if abs(got - EXPECTED_TOTAL) < 0.01:
        return CheckResult.ok(f"total correct: {got}")
    # Wrong total — peek at the downloaded file to distinguish "bad math" from
    # "this isn't the CSV" (e.g. an HTML page saved under sales.csv from a wrong URL).
    head = (read_guest_file(vm, f"{home}/Downloads/sales.csv") or "")[:200].lstrip()
    if head and ("<!doctype" in head.lower() or "<html" in head.lower() or head.startswith("<")):
        return CheckResult(False, 0.4, f"got {got}: downloaded file is HTML, not the CSV "
                                       "(wrong URL? the CSV is at /download or /sales.csv)")
    return CheckResult(False, 0.5, f"wrong total: got {got}, expected {EXPECTED_TOTAL}")


SCENARIO = Scenario(
    name="download", target="ubuntu", task=task, check=check, setup=setup,
    teardown=lambda ctx, vm: ctx.stop(), port=8001, tags=("web", "shell", "cross-app"),
    summary="browser download -> filesystem -> shell parse/sum -> persist -> report",
)
