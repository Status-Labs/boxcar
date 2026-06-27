# Scenario benchmark, evals & optimizers

Boxcar ships a small **benchmark suite** of real, multi-step computer-use tasks,
an **end-to-end eval runner** that scores an agent on them, and two **optimizers**
that tune the agent's policy. This doc explains how the pieces fit together.

```
scenarios/<name>/        a self-contained task: server.py (web) + scenario.py spec
scenarios/framework.py   Scenario / ScenarioContext / CheckResult + in-process serve
scenarios/registry.py    discovers every scenario; select() by name/target/tag
control/policy.py        the DSPy Signatures, action execution, LM + decider build
control/runner.py        the look->act loop (run_agent) returning a RunResult + trace
control/evals.py         drive the suite on a VM, score it, write a scorecard/report
control/optimize.py      compile-time optimizer over labeled first-actions (proxy)
control/bootstrap_rollouts.py   harvest demos from PASSING runs -> back into optimize
```

## What a scenario is

A `Scenario` (see `scenarios/framework.py`) bundles:

- **task** — the natural-language goal handed to the agent (a string, or a
  function of the run context so a web URL/port can be interpolated);
- **setup(ctx, vm)** — start the host-side mock server and/or reset guest state;
- **check(ctx, vm) → CheckResult** — read the *verifiable end state* and return
  `passed` + a `0..1` score (partial credit allowed);
- **teardown(ctx, vm)** — stop servers / clean up.

Web scenarios run a stdlib HTTP server **on the host**; the guest browser reaches
it at `http://10.0.2.2:<port>` (QEMU user-net gateway → host loopback) and their
state is a small JSON file the check reads back. Desktop/shell scenarios have no
server — their check reads the **guest** filesystem (or `gsettings`) over SSH.

The point of `check` is that success is *measured*, never assumed: a saved draft,
a downloaded-and-summed CSV, a created account with the right fields, a flipped
setting. Partial scores separate reasoning failures from grounding failures.

### The suite (Ubuntu)

| Scenario   | Tags                | What it exercises |
|------------|---------------------|-------------------|
| `webmail`  | web                 | OS login → web login → read a message → contextual reply → save draft |
| `download` | web, shell, cross-app | browser download → filesystem → shell parse/sum → persist → report |
| `invoices` | web, reason         | read a table → reason which row is Overdue → type the name → send |
| `signup`   | web, multi-page     | navigate a 3-page wizard, fill fields per page, tick terms, submit |
| `triage`   | web, reason, select | reason over 3 tickets → pick the critical one → set a `<select>` → submit |
| `expense`  | web, reason, math   | read a budget table → compute the over-budget overage → fill + submit |
| `editor`   | desktop, hard       | open the Text Editor → type exact content → Save As to a path |
| `settings` | desktop             | open Settings → Appearance → switch to Dark (verified via `gsettings`) |
| `files`    | desktop, hard       | open Files → click into `Workspace`/`inbox` → move a file to Trash (clicks folder/file grid cells) |

## Running the eval

Prereqs: a booted/spawned VM reachable over SSH+QMP (same env vars as
`agent_dspy.py`) and provider keys in `control/.env`.

```bash
# spawn a fresh Ubuntu instance and log it in to the desktop first, then:
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/x-qmp.sock \
  control/.venv/bin/python control/evals.py --target ubuntu          # whole suite

control/.venv/bin/python control/evals.py --target ubuntu --scenario webmail,signup
control/.venv/bin/python control/evals.py --target ubuntu --tag web
control/.venv/bin/python control/evals.py --target ubuntu --no-optimized   # baseline
```

Output is a scorecard plus a JSON report under `control/optim/reports/`:

```
scenario     result   score   steps   wall     tokens    cost      detail
---------------------------------------------------------------------------
webmail      PASS     1.00    12      95s      42000     $0.1200   draft saved (contextual)
signup       PASS     1.00    18      140s     61000     $0.1900   all 5 fields correct
triage       FAIL     0.60    40      210s     90000     $0.3000   right ticket but priority=''
---------------------------------------------------------------------------
2/3 passed | mean score 0.87 | total cost $0.6100
```

Flags: `--provider`, `--target`, `--scenario a,b`, `--tag t`, `--no-optimized`,
`--a11y`, `--max-steps N`, `--trace` (save per-step screenshots), `--dspy-evaluate`.

## The suite as a DSPy eval

End-to-end success is also a first-class **DSPy metric**. `evals.py` exposes
`ScenarioRunner` (a `dspy.Module` whose `forward(scenario_name)` runs a scenario
to completion and returns its verifiable score) and `scenario_metric`. With
`--dspy-evaluate` the suite runs through `dspy.Evaluate` (single-threaded — one
shared VM) so you can point a DSPy optimizer at *true task success*, not just the
per-step proxy below.

## Two optimizers

**1. Compile-time proxy — `optimize.py`.** Grades a single decision (screenshot →
the right *first* action) against a labeled set of real screens, rewarding the
reliable method (shell for scriptable work, `super` to open an app, `ctrl-l` to
navigate) over brittle coordinate clicks. Cheap (no VM), and it's what produces
`optimized_<target>.json` that the agent and the eval load automatically.

```bash
cd control
.venv/bin/python optimize.py --target ubuntu                  # MIPROv2 (instruction-only)
.venv/bin/python optimize.py --target ubuntu --method bootstrap
.venv/bin/python optimize.py --target ubuntu --eval-only       # just score the baseline
```

**2. Learn from successful rollouts — `bootstrap_rollouts.py`.** Closes the loop
with the benchmark: run the suite, and for every scenario that **passes**, keep
each step it took (the screen, the running history, the action that won) as a
labeled demo under `control/optim/rollouts/<target>/`. Those demos are folded back
into `optimize.py`'s trainset via `load_rollout_demos()`, so the optimizer learns
from real verified behavior, not only the hand-labeled screens.

```bash
# 1. harvest demos from passing runs (needs a VM)
control/.venv/bin/python control/bootstrap_rollouts.py --target ubuntu
# 2. recompile so the demos take effect
control/.venv/bin/python control/optimize.py --target ubuntu --method bootstrap
# 3. re-run the eval to confirm the score moved
control/.venv/bin/python control/evals.py --target ubuntu
```

The full loop is: **measure** (evals) → **harvest** the wins (bootstrap_rollouts)
→ **compile** (optimize) → **measure again**. Each pass turns verified successes
into a stronger policy.

## Adding a scenario

1. `mkdir scenarios/<name>` and add `__init__.py`.
2. For a web task, write `server.py` (stdlib only; keep state in a small JSON file
   it resets on start, and add a dump endpoint for manual verification).
3. Write `scenario.py` exposing `SCENARIO = Scenario(name=..., target=..., task=...,
   setup=..., check=...)`. The check must read a **verifiable** end state.
4. `registry.py` discovers it automatically. Add a host-only test to
   `scenarios/test_scenarios.py` (drive the HTTP flow, assert the check passes on a
   good run and fails on the empty state).

```bash
# host-only tests — no VM required, validate servers + scoring logic
control/.venv/bin/python -m scenarios.test_scenarios
```
