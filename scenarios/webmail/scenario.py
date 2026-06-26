"""Scenario spec for the mock-webmail "log in + draft a reply" flow.

Wraps the standalone server.py (its Handler + drafts.json) in the benchmark
framework so the eval runner can serve it in-process and score the saved draft.
"""
import json
import os

from ..framework import CheckResult, Scenario, ScenarioContext
from . import server

DRAFTS = server.DRAFTS


def setup(ctx: ScenarioContext, vm):
    if os.path.exists(DRAFTS):
        os.remove(DRAFTS)
    ctx.serve(server.Handler)


def task(ctx: ScenarioContext) -> str:
    return (f"Open the browser to {ctx.guest_url()}, sign in with demo/demo, open "
            "Dana's email, write a reply agreeing to lunch on Tuesday at noon, and "
            "click Save draft.")


def check(ctx: ScenarioContext, vm) -> CheckResult:
    if not os.path.exists(DRAFTS):
        return CheckResult.fail("no draft was saved (drafts.json missing)")
    drafts = json.load(open(DRAFTS))
    if not drafts:
        return CheckResult.fail("drafts.json is empty — Save draft never fired")
    body = (drafts[-1].get("body") or "").lower()
    if len(body.strip()) < 10:
        return CheckResult(False, 0.5, "a draft was saved but the body is essentially empty")
    contextual = "tuesday" in body or "lunch" in body or "noon" in body
    return CheckResult(True, 1.0 if contextual else 0.7,
                       f"draft saved ({'contextual' if contextual else 'generic'}): "
                       f"{drafts[-1].get('body', '')[:60]!r}")


SCENARIO = Scenario(
    name="webmail", target="ubuntu", task=task, check=check, setup=setup,
    teardown=lambda ctx, vm: ctx.stop(), port=8000, tags=("web",),
    summary="OS login -> web login -> read a message -> contextual reply -> save draft",
)
