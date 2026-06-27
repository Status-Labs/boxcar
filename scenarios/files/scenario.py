"""Scenario spec: navigate GNOME Files by clicking, then act on a file.

A pure **desktop-app navigation** flow — no host server. The agent opens Files
(super -> "Files"), double-clicks down two folders (`Workspace` -> `inbox`), and
moves a single file (`obsolete.txt`) to the Trash by selecting it and pressing
Delete. The end state is verifiable over SSH: `obsolete.txt` must leave `inbox`
while `keep.txt` stays.

This is the click-bound counterpart to `editor` (which is keyboard-heavy): the
only way through the GUI is to land clicks on folder/file **grid cells**, so it
cleanly exercises the GTK4/libadwaita rect recovery (`config/ubuntu/atspi_helper.py`)
— double-clicking the folder cells to descend, then clicking the file cell to
select it. A capable agent could also satisfy the end state via the shell (`rm`);
the step trace in the eval report shows which path it took.
"""
from ..framework import CheckResult, Scenario, ScenarioContext, guest_path_exists

# Two-level click chain from Home: Workspace -> inbox. `obsolete.txt` is the
# target; `keep.txt` is the bystander that must survive.
ROOT = "Workspace"
SUB = "inbox"
TARGET = "obsolete.txt"
KEEP = "keep.txt"
DECOYS = ("reports", "media")  # sibling folders so the right one must be chosen


def _dir(vm):
    return f"/home/{vm.username}/{ROOT}/{SUB}"


def setup(ctx: ScenarioContext, vm):
    # Close any open Files window so the run starts from a clean Home view — a
    # stale Nautilus window left over from a prior run/sample shows the old
    # (now recreated) folder and makes navigation non-deterministic.
    vm.run(f"pkill -u {vm.username} nautilus 2>/dev/null; true")
    # Rebuild the tree from scratch so a re-run can't pass on a stale state and
    # `obsolete.txt` is freshly present (so the pre-check fails as it should).
    base = f"/home/{vm.username}/{ROOT}"
    vm.run(f"rm -rf {base}")
    for d in (*DECOYS, SUB):
        vm.run(f"mkdir -p {base}/{d}")
    vm.run(f"printf 'keep me\\n'   > {base}/{SUB}/{KEEP}")
    vm.run(f"printf 'delete me\\n' > {base}/{SUB}/{TARGET}")


def task(ctx: ScenarioContext) -> str:
    return (
        "Open the Files app (GNOME Files / Nautilus). Starting from your Home "
        f"folder, open the `{ROOT}` folder, then open the `{SUB}` folder inside "
        f"it. In `{SUB}`, move the file `{TARGET}` to the Trash (select it and "
        f"press the Delete key). Leave `{KEEP}` untouched.")


def check(ctx: ScenarioContext, vm) -> CheckResult:
    d = _dir(vm)
    target_gone = not guest_path_exists(vm, f"{d}/{TARGET}")
    keep_present = guest_path_exists(vm, f"{d}/{KEEP}")
    if target_gone and keep_present:
        return CheckResult.ok(f"{TARGET} removed, {KEEP} left intact")
    if target_gone and not keep_present:
        # Goal met but it took the bystander down too — partial credit.
        return CheckResult(True, 0.6, f"{TARGET} removed, but {KEEP} was also deleted")
    if not target_gone and not keep_present:
        return CheckResult.fail(f"deleted the wrong file ({KEEP}); {TARGET} still in {SUB}")
    return CheckResult.fail(f"{TARGET} is still in {SUB}")


SCENARIO = Scenario(
    name="files", target="ubuntu", task=task, check=check, setup=setup,
    tags=("desktop", "hard"),
    summary="open Files -> click into Workspace/inbox -> move obsolete.txt to Trash",
)
