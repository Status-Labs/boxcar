# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`files` scenario — click-bound Files navigation.** A desktop task that opens
  GNOME Files, descends two folders by double-clicking (`~/Workspace` → `inbox`),
  and moves `obsolete.txt` to the Trash while leaving `keep.txt` intact (verified
  over SSH). Unlike the keyboard-heavy `editor`, the GUI path requires landing
  clicks on folder/file **grid cells**, so it cleanly showcases the GTK4 rect
  recovery (PR #2). Tagged `desktop, hard`.
- **Scenario benchmark suite + end-to-end evals.** A `Scenario` framework
  (`scenarios/framework.py`, `registry.py`) turns each task into a scored
  benchmark with a verifiable end-state check. New complex workflows: a
  multi-page sign-up wizard (`signup`), issue triage with a `<select>` (`triage`),
  expense-report arithmetic (`expense`), and two desktop-app tasks (`editor`,
  `settings`) — plus the existing webmail/download/invoices adapted into the suite.
- **End-to-end eval runner** (`control/evals.py`): drives the agent through the
  suite on a live VM, scores each run, prints a scorecard, writes a JSON report,
  and exposes the suite as a `dspy.Evaluate` program (`ScenarioRunner`).
- **Rollout-bootstrapping optimizer** (`control/bootstrap_rollouts.py`): harvests
  labeled demos from *passing* end-to-end runs and folds them into
  `optimize.py`'s trainset; expanded the optimizer dataset with workflow
  decision-points. See `docs/evals.md`.
- Host-only scenario tests (`scenarios/test_scenarios.py`) — validate the mock
  servers and scoring logic without a VM.
- **`Makefile`** wrapping the common flows (`up`/`down`/`reset`/`recreate`,
  `eval`/`agent`/`bootstrap`, `test`/`lint`/`optimize`/`clean`). It derives a
  clone's SSH port (from the running qemu cmdline) and QMP socket path from the
  instance name, so the verbose `VM_SSH_PORT=…/VM_QMP_SOCK=…` env vars are gone.
- **Stall detection** in the agent loop (`runner.py`): repeating the same no-op
  action injects an escalating corrective hint and aborts early (configurable via
  `AGENT_STALL_WARN`/`AGENT_STALL_ABORT`), instead of burning all 40 steps.
- Open-source project scaffolding: MIT `LICENSE`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, and a `CHANGELOG.md`.
- GitHub issue templates (bug report, feature request), pull request template,
  and a CI workflow (`flake8` + `compileall`, advisory shellcheck).
- Rebranded the project to **Boxcar** with an updated README.

### Changed
- Refactored the DSPy agent into reusable modules: `control/policy.py` (Signatures,
  action execution, LM/decider construction) and `control/runner.py` (the
  look→act loop as `run_agent`, returning a scored `RunResult` with a step trace).
  `agent_dspy.py` is now a thin CLI over them (behavior unchanged).
- Cleaned up Python style so the repository passes `flake8` (config in
  `setup.cfg`).

### Fixed
- **Chrome first-run modal blocked browser scenarios.** A fresh Chrome profile
  showed a full-window "Sign in to Chrome" dialog, hiding the address bar so the
  agent looped on `ctrl-l`. `provision.sh` now also bakes
  `--no-first-run --no-default-browser-check` into the launcher (belt-and-suspenders
  to the existing managed policy), and the Ubuntu guide tells the agent to dismiss
  the dialog / not repeat `ctrl-l`. (Re-bake the golden image to pick this up.)
- **`download` scenario served HTML for unknown paths.** The CSV was only at
  `/download`; any other path returned the page with a 200, so a shell
  `curl …/sales.csv` saved HTML and summed to a bogus 0.0. The CSV is now served
  at `/sales.csv` too and unknown paths 404; the check reports an HTML-not-CSV
  download explicitly.
- **Form-interaction hardening** (from end-to-end run traces; suite now 8/8 on
  gpt-5 at `reasoning_effort=medium`):
  - Chrome "Save password?" prompt interrupted multi-page form flows —
    `provision.sh` policy now sets `PasswordManagerEnabled: false`.
  - The guide's form-filling section now teaches type-after-one-click, Tab
    between fields, and a GTK `Ctrl+L` Save-As recipe (fixed the editor scenario).
- **Save-As / Files guidance hardened against flailing.** The GTK Save-As recipe
  in `control/guides/ubuntu.md` is now a strict numbered sequence (Ctrl+L once →
  full path → Enter → click Save) with explicit "press Ctrl+L only once" and
  "never click Cancel" rules — the two failure modes seen in `editor` traces. The
  Nautilus section was also updated: now that folder/file cells are grounded (the
  GTK4 rect recovery, PR #2), it teaches **double-click to open a folder** and
  click-to-select + Delete-to-Trash, instead of the old "don't click folder
  icons" workaround.
  - `signup` made agent-friendly per the project's "one unambiguous target"
    principle: autofocus the first field of each wizard step, a large clickable
    terms row instead of a bare checkbox, and a 60-step budget for the longest flow.
