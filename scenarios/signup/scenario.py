"""Scenario spec: multi-page sign-up wizard (Account -> Profile -> Review -> Create)."""
import json
import os

from ..framework import CheckResult, Scenario, ScenarioContext
from . import server

ACCOUNTS = server.ACCOUNTS

# The target account the agent is asked to create.
WANT = {
    "username": "jdoe",
    "email": "jdoe@acme.example",
    "full_name": "Jane Doe",
    "company": "Acme",
    "role": "Engineer",
}


def setup(ctx: ScenarioContext, vm):
    if os.path.exists(ACCOUNTS):
        os.remove(ACCOUNTS)
    ctx.serve(server.Handler)


def task(ctx: ScenarioContext) -> str:
    return (f"Open {ctx.guest_url()} and complete the sign-up wizard. On step 1 enter "
            "username 'jdoe', email 'jdoe@acme.example', and password 'Hunter2!'. On step "
            "2 enter full name 'Jane Doe', company 'Acme', role 'Engineer'. On step 3, tick "
            "'I agree to the terms of service' and click Create account.")


def check(ctx: ScenarioContext, vm) -> CheckResult:
    if not os.path.exists(ACCOUNTS):
        return CheckResult.fail("no account created (accounts.json missing) — "
                                "the wizard was never completed")
    accounts = json.load(open(ACCOUNTS))
    if not accounts:
        return CheckResult.fail("accounts.json is empty")
    rec = accounts[-1]
    if not rec.get("agree"):
        return CheckResult(False, 0.4, "account created but terms not accepted")
    hits = [f for f, v in WANT.items()
            if (rec.get(f, "") or "").strip().lower() == v.lower()]
    score = len(hits) / len(WANT)
    if score == 1.0:
        return CheckResult.ok(f"all {len(WANT)} fields correct for {rec.get('username')!r}")
    missed = [f for f in WANT if f not in hits]
    return CheckResult(score >= 0.8, score,
                       f"{len(hits)}/{len(WANT)} fields correct; wrong/missing: {missed}")


SCENARIO = Scenario(
    name="signup", target="ubuntu", task=task, check=check, setup=setup,
    teardown=lambda ctx, vm: ctx.stop(), port=8003, tags=("web", "multi-page"),
    # The longest flow: 3 pages x several fields + a checkbox + submit. Give it
    # more headroom than the 40-step default so it isn't cut off mid-wizard.
    max_steps=60,
    summary="navigate a 3-page wizard, fill fields per page, tick terms, submit",
)
