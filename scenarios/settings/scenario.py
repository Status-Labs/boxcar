"""Scenario spec: change a GNOME setting via the Settings app.

A **desktop-app navigation** flow — no host server. The agent opens Settings
(super -> "Settings"), goes to Appearance, and selects the Dark style. The end
state is verifiable over SSH via gsettings, with no file artifact to fake:
``org.gnome.desktop.interface color-scheme`` must become ``prefer-dark``.

`setup` forces the start state to light (``default``) so flipping to dark is a
real change. (As with the other desktop scenario, the shell could also flip this;
the step trace shows whether the agent navigated the GUI.)
"""
from ..framework import CheckResult, Scenario, ScenarioContext

KEY = "org.gnome.desktop.interface color-scheme"
WANT = "prefer-dark"


def _session(vm):
    # Run a gsettings command inside the logged-in GNOME session (needs the
    # session DBUS address; LinuxVM exposes that prefix).
    return vm._session_env()  # noqa: SLF001


def setup(ctx: ScenarioContext, vm):
    vm.run(_session(vm) + f"gsettings set {KEY} default")


def task(ctx: ScenarioContext) -> str:
    return ("Open the Settings app, go to the Appearance section, and switch the "
            "system style to Dark.")


def check(ctx: ScenarioContext, vm) -> CheckResult:
    rc, out, _ = vm.run(_session(vm) + f"gsettings get {KEY}")
    val = (out or "").strip().strip("'\"")
    if rc != 0:
        return CheckResult.fail("could not read color-scheme via gsettings")
    if val == WANT:
        return CheckResult.ok(f"color-scheme = {val}")
    return CheckResult(False, 0.0, f"color-scheme is {val!r}, expected {WANT!r}")


SCENARIO = Scenario(
    name="settings", target="ubuntu", task=task, check=check, setup=setup,
    tags=("desktop",),
    summary="open Settings -> Appearance -> switch to Dark (verified via gsettings)",
)
