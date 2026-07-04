"""Scenario spec: drive the GNOME Text Editor to create and save a file.

A pure **desktop-app** flow — no host server. The agent opens the Text Editor
(super -> "Text Editor"), types two exact lines, and uses Save As to write the
file to ~/Desktop/poem.txt. `check` reads that file back over SSH.

The hard part is grounding: typing into the editor and driving the GTK Save
dialog to an exact path. (A capable agent could also satisfy the end state via
the shell; the step trace in the eval report shows which path it took.)
"""
from ..framework import CheckResult, Scenario, ScenarioContext, read_guest_file

LINE1 = "Roses are red, violets are blue,"
LINE2 = "this VM is driven by an LLM for you."
REL_PATH = "Desktop/poem.txt"


def _path(vm):
    return f"/home/{vm.username}/{REL_PATH}"


def setup(ctx: ScenarioContext, vm):
    # Close any Text Editor / Save dialog left open by a prior run/sample, so each
    # run starts from an empty editor. A leftover window (stale text, an open Save
    # dialog) makes the run non-deterministic and lets the agent skip straight to
    # saving — or assume the task is already done and no-op.
    # NB (both live-diagnosed):
    #  * -f (match full cmdline) is required — the comm is truncated to 15 chars
    #    ("gnome-text-edit"), so a plain `pkill gnome-text-editor` matches nothing.
    #    But a bare -f pattern ALSO matches this command's own `bash -c` wrapper
    #    over SSH (the cmdline contains the pattern) and kills it mid-chain — the
    #    [g] bracket keeps the pattern from matching itself.
    #  * -9, not TERM: on graceful exit the editor SAVES its session, and the next
    #    launch restores the previous sample's document — cross-sample text
    #    contamination (doubled content). SIGKILL + removing the session state dir
    #    guarantees the next sample opens an empty editor.
    vm.run(f"pkill -9 -u {vm.username} -f '[g]nome-text-editor' 2>/dev/null; true")
    vm.run(f"rm -rf /home/{vm.username}/.local/share/org.gnome.TextEditor")
    # Clean any leftover from a previous run so the check can't pass stale.
    vm.run(f"rm -f {_path(vm)}")


def task(ctx: ScenarioContext) -> str:
    return (
        "Open the Text Editor (GNOME) and type exactly these two lines:\n"
        f"{LINE1}\n{LINE2}\n"
        f"Then save the file to ~/{REL_PATH} (use Save As and type that path).")


def _norm(s: str) -> str:
    return "\n".join(line.rstrip() for line in s.strip().splitlines())


def check(ctx: ScenarioContext, vm) -> CheckResult:
    content = read_guest_file(vm, _path(vm))
    if content is None:
        return CheckResult.fail(f"~/{REL_PATH} was not created")
    got = _norm(content)
    want = _norm(f"{LINE1}\n{LINE2}")
    if got == want:
        return CheckResult.ok("file saved with exact content")
    # Partial credit if both lines are present even with extra whitespace/lines.
    if LINE1 in content and LINE2 in content:
        return CheckResult(True, 0.8, "both lines present (minor formatting differences)")
    present = sum(x in content for x in (LINE1, LINE2))
    return CheckResult(False, 0.2 * present,
                       f"content mismatch ({present}/2 lines present): {content[:80]!r}")


SCENARIO = Scenario(
    name="editor", target="ubuntu", task=task, check=check, setup=setup,
    tags=("desktop", "hard"),
    summary="open the Text Editor -> type exact content -> Save As to a path",
)
