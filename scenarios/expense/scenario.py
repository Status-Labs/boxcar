"""Scenario spec: find the over-budget category and report the overage amount."""
import json
import os
import re

from ..framework import CheckResult, Scenario, ScenarioContext
from . import server

LOG = server.LOG


def setup(ctx: ScenarioContext, vm):
    if os.path.exists(LOG):
        os.remove(LOG)
    ctx.serve(server.Handler)


def task(ctx: ScenarioContext) -> str:
    return (f"Open {ctx.guest_url()}. Review the spend-by-category table and find the one "
            "category that is over its monthly budget. In the report form, enter that "
            "category name and the overage amount (spent minus budget), then Submit report.")


def check(ctx: ScenarioContext, vm) -> CheckResult:
    if not os.path.exists(LOG):
        return CheckResult.fail("no report submitted (report.json missing)")
    recs = json.load(open(LOG))
    if not recs:
        return CheckResult.fail("report.json is empty")
    rec = recs[-1]
    cat_ok = (rec.get("category", "") or "").strip().lower() == server.OVER_CATEGORY.lower()
    m = re.search(r"-?\d+(?:\.\d+)?", (rec.get("amount", "") or "").replace(",", ""))
    amt_ok = bool(m) and abs(float(m.group()) - server.OVER_AMOUNT) < 0.01
    if cat_ok and amt_ok:
        return CheckResult.ok(f"{server.OVER_CATEGORY} over by {server.OVER_AMOUNT}")
    if cat_ok:
        return CheckResult(False, 0.6,
                           f"right category but amount={rec.get('amount')!r} "
                           f"(want {server.OVER_AMOUNT})")
    if amt_ok:
        return CheckResult(False, 0.4, f"right amount but category={rec.get('category')!r}")
    return CheckResult(False, 0.1, f"wrong category and amount: {rec}")


SCENARIO = Scenario(
    name="expense", target="ubuntu", task=task, check=check, setup=setup,
    teardown=lambda ctx, vm: ctx.stop(), port=8005, tags=("web", "reason", "math"),
    summary="read a budget table -> compute the over-budget overage -> fill + submit",
)
