"""Scenario spec: read several tickets, reason which is critical, triage it High."""
import json
import os

from ..framework import CheckResult, Scenario, ScenarioContext
from . import server

LOG = server.LOG


def setup(ctx: ScenarioContext, vm):
    if os.path.exists(LOG):
        os.remove(LOG)
    ctx.serve(server.Handler)


def task(ctx: ScenarioContext) -> str:
    return (f"Open {ctx.guest_url()}, read the open tickets, and decide which one is a "
            "critical production outage. In the triage form, select that ticket and set "
            "its Priority to High, then click Submit triage.")


def check(ctx: ScenarioContext, vm) -> CheckResult:
    if not os.path.exists(LOG):
        return CheckResult.fail("nothing triaged (triage.json missing)")
    recs = json.load(open(LOG))
    if not recs:
        return CheckResult.fail("triage.json is empty")
    rec = recs[-1]
    right_ticket = rec.get("ticket") == server.CRITICAL_ID
    high = (rec.get("priority") or "").lower() == "high"
    if right_ticket and high:
        return CheckResult.ok(f"ticket #{server.CRITICAL_ID} triaged High")
    if right_ticket:
        return CheckResult(False, 0.6, f"right ticket but priority={rec.get('priority')!r}")
    if high:
        return CheckResult(False, 0.4, f"High set, but on wrong ticket #{rec.get('ticket')}")
    return CheckResult(False, 0.2, f"wrong ticket and priority: {rec}")


SCENARIO = Scenario(
    name="triage", target="ubuntu", task=task, check=check, setup=setup,
    teardown=lambda ctx, vm: ctx.stop(), port=8004, tags=("web", "reason", "select"),
    summary="reason over 3 tickets -> pick the critical one -> set a <select> -> submit",
)
