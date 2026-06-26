"""Scenario spec for the read -> extract -> act (invoice reminder) flow.

The agent must read the table, work out which customer is Overdue (Globex Inc),
type that name into the single reminder form, and Send. The server records the
typed name to reminders.json, which `check` reads.
"""
import json
import os

from ..framework import CheckResult, Scenario, ScenarioContext
from . import server

LOG = server.LOG
EXPECTED = "Globex Inc"


def setup(ctx: ScenarioContext, vm):
    if os.path.exists(LOG):
        os.remove(LOG)
    ctx.serve(server.Handler)


def task(ctx: ScenarioContext) -> str:
    return (f"Open {ctx.guest_url()}, read the invoices table, find the customer whose "
            "status is Overdue, type that name into the 'Send a reminder to' box, and "
            "click Send reminder.")


def check(ctx: ScenarioContext, vm) -> CheckResult:
    if not os.path.exists(LOG):
        return CheckResult.fail("no reminder was sent (reminders.json missing)")
    recs = json.load(open(LOG))
    if not recs:
        return CheckResult.fail("reminders.json is empty")
    got = (recs[-1].get("customer") or "").strip()
    if got.lower() == EXPECTED.lower():
        return CheckResult.ok(f"correct customer: {got!r}")
    return CheckResult(False, 0.3, f"wrong customer: got {got!r}, expected {EXPECTED!r}")


SCENARIO = Scenario(
    name="invoices", target="ubuntu", task=task, check=check, setup=setup,
    teardown=lambda ctx, vm: ctx.stop(), port=8002, tags=("web", "reason"),
    summary="read a table -> reason which row is Overdue -> type the name -> send",
)
