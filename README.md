# 🚃 Boxcar

**A disposable desktop sandbox where LLM agents drive a real Windows 11 or Ubuntu machine.**

[![CI](https://github.com/Status-Labs/boxcar/actions/workflows/ci.yml/badge.svg)](https://github.com/Status-Labs/boxcar/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Boxcar is a single-script QEMU/KVM setup that boots a Windows 11 or Ubuntu
Desktop VM, then hands the keyboard, mouse, and shell to an LLM so it can
complete real GUI tasks on its own (computer-use). Bake a provisioned VM into a
golden image once and **spawn fresh, disposable instances in seconds** as
copy-on-write overlays — each one a clean, throwaway "boxcar" for an agent to
work in.

**Highlights**

- 🖥️ **One script per VM** — `./win11.sh` / `./ubuntu.sh`, fully unattended installs.
- 🤖 **Provider-agnostic agent** — Anthropic, OpenAI, or any OpenAI-compatible
  endpoint; Windows (PowerShell/SSH) and Ubuntu (bash) targets.
- ⚡ **Golden images** — bake once, spawn disposable CoW clones in milliseconds.
- 🧠 **DSPy variant** — an optimizable policy you can compile per-OS.
- 📊 **Scored benchmark suite** — 8 real tasks with verifiable end-states, an
  end-to-end eval runner (scorecard + JSON report), and a rollout-bootstrapping
  optimizer. See [docs/evals.md](docs/evals.md).
- ♿ **Accessibility trees** — opt-in AT-SPI / UI Automation grounding (`--a11y`).
- 🎬 **Ready-made scenarios** — webmail, downloads, invoices, a multi-page sign-up
  wizard, issue triage, expense reporting, and desktop-app tasks.

> ⚠️ Boxcar lets an LLM run arbitrary commands and control a desktop inside a VM.
> The VM is a sandbox, not a hardened security boundary — see [SECURITY.md](SECURITY.md).

Each VM is a single script. Disks, UEFI vars, and TPM state live in `vms/`.

## What's included

| File              | Purpose                                              |
|-------------------|------------------------------------------------------|
| `win11.sh`        | Run / install / bake the Windows 11 VM (UEFI + TPM)  |
| `ubuntu.sh`       | Run / install / bake the Ubuntu Desktop VM (autoinstall) |
| `spawn.sh`        | Spawn fast VMs from a baked base (CoW overlays)      |
| `lib/common.sh`   | Shared config (paths, KVM, disk, UEFI, swtpm)        |
| `lib/qmp.py`      | QMP helper (auto-keypress, screenshots)              |
| `control/winvm.py`| Python library to fully control the Windows VM       |
| `control/agent.py`| Let an LLM drive the VM autonomously (computer-use)  |
| `control/agent_dspy.py`| Same agent built with DSPy (CLI over `policy` + `runner`) |
| `control/policy.py`| DSPy Signatures, action execution, LM + decider construction |
| `control/runner.py`| The look→act→look loop (`run_agent`) returning a scored `RunResult` |
| `control/evals.py`| **End-to-end benchmark**: drive the scenario suite on a VM, score it, scorecard |
| `control/optimize.py`| Compile-time optimizer — tunes the agent's policy (per-OS) |
| `control/bootstrap_rollouts.py`| Harvest demos from *passing* runs → back into the optimizer |
| `control/os_context.py`| Loads the per-OS agent guide (single source of truth) |
| `control/guides/*.md`| Editable OS "user guides" given to the agent as context |
| `scenarios/framework.py`| Scenario spec (`task`/`setup`/`check`) + in-process host server |
| `scenarios/registry.py`| Discovers every scenario; `select()` by name/target/tag |
| `scenarios/webmail/`| Self-contained demo: log in + draft an email reply    |
| `scenarios/download/`| Cross-app demo: browser download → process in the shell |
| `scenarios/invoices/`| Read→extract→act demo: find the overdue row, act on it |
| `scenarios/signup/`| Multi-page web wizard: Account → Profile → Review → Create |
| `scenarios/triage/`| Reason over tickets → pick the critical one → set a `<select>` |
| `scenarios/expense/`| Read a budget table → compute the overage → file a report |
| `scenarios/editor/`| Desktop app: Text Editor → type content → Save As to a path |
| `scenarios/settings/`| Desktop app: Settings → Appearance → Dark (verified via `gsettings`) |
| `control/backends.py`| LLM provider adapters (Anthropic / OpenAI / compat) |
| `isos/`           | Installer ISOs (git-ignored)                         |
| `vms/<type>/`     | Per-VM state: `disk.qcow2`, `vars.fd`, `tpm/`, `base.qcow2`, `clones/` |

## Requirements (already present on this machine)

- `qemu-system-x86_64`, `qemu-img`, `swtpm`, OVMF firmware
- `/dev/kvm` access (hardware acceleration)
- ISOs in `isos/` (git-ignored, self-contained in this project):
  - `Win11_25H2_English_x64_v2.iso`
  - `virtio-win-0.1.285.iso` (Windows virtio drivers)
  - `ubuntu-24.04.4-desktop-amd64.iso`

## Usage

A **`Makefile`** wraps the common flows so you don't have to retype the
`VM_SSH_PORT=… VM_QMP_SOCK=…` env vars — it derives the SSH port and QMP socket
from a clone's name. `make help` lists everything; the essentials:

```bash
make up                      # spawn a fresh disposable ubuntu clone "eval" (background)
make eval                    # run the whole scored scenario suite against it
make eval SCENARIO=webmail EVAL_ARGS=--trace   # one scenario, save step screenshots
make agent TASK="open a terminal and report the date"
make recreate                # tear down + bring back a clean clone
make down                    # stop it
make test                    # host-only scenario tests (no VM)
make lint                    # flake8 + compileall (mirrors CI)
```

Override `TARGET=win11`, `NAME=<instance>`, or `PROVIDER=openai` on any target.
The raw scripts below still work if you prefer them.

First time (boots the installer ISO):

```bash
./ubuntu.sh install
./win11.sh install
```

After the OS is installed, just run:

```bash
./ubuntu.sh
./win11.sh
```

The disk (80G Windows / 64G Ubuntu) and UEFI vars are created automatically on
first run; the scripts are idempotent.

## Windows 11 install (unattended)

`./win11.sh install` is **100% hands-off** via `config/autounattend.xml`, which
is burned to a small CD (`vms/win11-unattend.iso`) that Windows Setup
auto-detects. It wipes the disk, lays out UEFI/GPT partitions, loads the
virtio-scsi driver, installs Windows 11 Pro, creates a local admin, and skips
the Microsoft account.

There is **no manual step** — the one-time *"Press any key to boot from CD…"*
prompt is auto-pressed for you over the VM's QMP control socket (see
`lib/qmp.py`). Just run it and wait for the desktop.

- **Login:** `user` / `user`
- Edit `config/autounattend.xml` to change the username, locale, computer name,
  etc. The CD is rebuilt automatically whenever that file changes.
- To start completely fresh: `./win11.sh purge` then `./win11.sh install`.

### Automated software + machine config

`config/provision.ps1` runs automatically at first logon (it's on the unattend
CD; the answer file's `FirstLogonCommands` launches it). By default it:

1. installs the virtio guest tools (network / display / balloon drivers),
2. waits for internet,
3. installs **Chocolatey**,
4. installs the packages in its `$Packages` list (default: `nodejs-lts`, `git`),
5. applies config tweaks (show file extensions, enable RDP, never sleep).

To customise, edit `config/provision.ps1`:
- add Chocolatey package names to `$Packages` (e.g. `vscode`, `python`, `7zip`),
- add your own commands to the CONFIG section.

The unattend CD is rebuilt automatically when you change the script. Output is
logged inside the VM at `C:\provision.log`.

> The guest tools install happens inside `provision.ps1`, so a fully unattended
> install needs no manual driver step. If you ever install manually, run
> `virtio-win-guest-tools.exe` from the virtio-win CD yourself.

## Controlling the VM from Python (`control/winvm.py`)

`WinVM` gives you full programmatic control of the running Windows VM over two
channels:

- **QMP** (host → VM hardware): `screenshot()`, `click(x, y)`, `type(text)`,
  `key(...)`. Works even at the login screen; nothing needed in the guest.
- **SSH** (into Windows): `run(cmd)`, `powershell(script)`, `upload()`,
  `download()`. Uses OpenSSH (auto-enabled by `provision.ps1`) via the
  port-forward `127.0.0.1:2222 → guest:22` set in `win11.sh`.

Setup (one time):

```bash
cd control
python3 -m venv --without-pip .venv
.venv/bin/python <(curl -sS https://bootstrap.pypa.io/get-pip.py)
.venv/bin/python -m pip install -r requirements.txt
```

Use it (VM must be running — `./win11.sh`):

```python
from winvm import WinVM
vm = WinVM()                                  # user/user, port 2222
print(vm.powershell("node --version"))        # run code in the guest
vm.screenshot("shot.png")                     # capture the screen
vm.run("start notepad"); vm.sleep(2)
vm.type("Hello from Python!")                 # drive the GUI
vm.upload("local.txt", "C:/Users/user/x.txt") # copy files in
```

Run the included demo: `control/.venv/bin/python control/demo.py`.

Default login is `user`/`user`; change it in `config/autounattend.xml` (and
pass new creds to `WinVM(...)`).

## Letting an LLM control the VM (`control/agent.py`)

`agent.py` connects an LLM to `WinVM` so it can drive the machine on its own.
The model gets tools — `screenshot`, `left_click`, `double_click`, `type_text`,
`key`, and `run_powershell` — and runs an agentic loop: **screenshot → decide →
act → screenshot again**, until your task is done. Screenshots are sent back as
images so the model can see the desktop and react. It prefers `run_powershell`
(over SSH) for scriptable work and the mouse/keyboard tools for GUI-only steps.

It is **provider-agnostic** (`control/backends.py`): Anthropic, OpenAI, or any
OpenAI-compatible endpoint — and **target-aware**: `--target win11` (default) or
`--target ubuntu`. The Windows target runs PowerShell over SSH; the Ubuntu
target runs bash. `control/winvm.py` provides a shared `VM` base with `WinVM`
and `LinuxVM` subclasses.

```bash
# Windows (default)
.venv/bin/python agent.py "Open Notepad and write a haiku, save to Desktop"
# Ubuntu — point at a spawned instance's port/socket
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/x-qmp.sock \
  .venv/bin/python agent.py --target ubuntu "Create ~/Desktop/notes.txt with today's date"
```

**Configure once** — copy the template and fill in your keys. `agent.py` and
`demo.py` load `control/.env` automatically:

```bash
cd control
cp .env.example .env        # then edit .env and add your API key(s)
.venv/bin/python agent.py "Open Notepad, write a haiku about VMs, save it to the Desktop"
```

`.env` (git-ignored) sets the default provider, model, keys, and VM connection.
Real environment variables and the `--provider` flag override it per run:

```bash
.venv/bin/python agent.py --provider openai "..."         # one-off provider switch
OPENAI_MODEL=gpt-4.1 .venv/bin/python agent.py "..."      # one-off model override
```

For a local/compatible server, set in `.env`:
`OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_MODEL=llama3.2-vision`,
`AGENT_PROVIDER=openai` (the model must support vision).

To add another provider, implement a small class with a `step()` method in
`backends.py` and register it in `make_backend()`. Edit the `TOOLS` list or
`system` prompt in `agent.py` to change capabilities/behavior.

### DSPy variant (`control/agent_dspy.py`)

Same `WinVM`/`LinuxVM` execution and same `.env` — but the decision is a
**DSPy `Signature`** instead of a hand-written tool loop. Each step feeds the OS
guidance, the task, the history, and the *current screenshot* (`dspy.Image`) into
`NextAction → (done, tool, args, note)`; we run the action and loop. DSPy reaches
any provider through **LiteLLM**, so the model is just a string
(`openai/gpt-4o`, `anthropic/claude-opus-4-8`), and the program is optimizable
with DSPy's tooling.

```bash
cp .env.example .env        # same config as agent.py
.venv/bin/python agent_dspy.py --target ubuntu "Report the Node.js version"
.venv/bin/python agent_dspy.py --provider openai "Open Notepad and write a haiku"
```

`agent.py` is the lightweight, dependency-minimal option (provider SDKs only);
`agent_dspy.py` adds DSPy + LiteLLM (in `requirements.txt`). Both are
target-aware (`--target win11|ubuntu`).

#### Optimizing the policy (`control/optimize.py`)

Because the decision is a DSPy program, it can be **compiled**. `optimize.py`
holds a labeled dataset — real screenshots (`control/optim/screens/`) → the
correct action for common tasks — and an **args-level** metric (right tool, and
for keyboard/shell actions the right key / a real script). Two optimizers:

```bash
cd control
.venv/bin/python optimize.py                      # MIPROv2 (instruction-only) — default
.venv/bin/python optimize.py --method bootstrap   # BootstrapFewShot (few-shot demos)
```

The dataset spans **common + complex tasks** (logins, app-launch, browser
shortcuts, and multi-step work like "write & run a Node script", "install &
verify a package"); the guides carry matching **recipes** so the agent knows how
to do them. Optimization is **per-OS**: `--target win11|ubuntu` (default: both)
trains on that OS's examples and writes `optimized_<target>.json` (git-ignored,
regenerable), which `agent_dspy.py` **auto-loads** for the matching target. So
Windows and Ubuntu get independently-tuned policies — no cross-OS demo leakage.
MIPROv2 needs `optuna` (in `requirements.txt`). Use `--eval-only` to just score.

**What we found (gpt-4o, common-tasks set) — context beat optimization:**

1. With the *old terse* prompt, Ubuntu baseline was **83%**; the miss was a
   **grounding** error ("open the Files app" → model clicks a dock icon instead
   of pressing Super). Neither MIPROv2 nor BootstrapFewShot fixed it — the rule
   was already in the prompt, so rewording/demos didn't help.
2. Moving the OS knowledge into a real **user guide** (`control/guides/ubuntu.md`,
   which names the Files app and says "open via Super → type name") lifted the
   baseline to **100%** (Ubuntu and Windows). The context fixed what the
   optimizer could not.

Takeaways:
- **Invest in the OS guides first.** They're the agent's domain knowledge and the
  cheapest, highest-leverage fix for grounding misses. Just edit the markdown.
- **MIPROv2 is the right optimizer when headroom remains** — it tunes only the
  instruction (`max_*_demos=0`), giving a ~1.5K artifact with **no extra images
  per call**, vs BootstrapFewShot's ~500K (demo screenshots inlined). With the
  guides in place, gpt-4o already scores 100% here, so there's nothing left to
  optimize; grow `DATA` (and try `--provider anthropic`) to find new headroom.

#### End-to-end benchmark + rollout loop (`control/evals.py`)

`optimize.py` grades a *single action* against a label — a cheap proxy. The
**benchmark** grades the whole task: `evals.py` drives the agent through the
[scenario suite](docs/evals.md) on a live VM and scores each run by its
**verifiable end state** (a saved draft, a created account, a flipped setting),
emitting a scorecard + JSON report. The same suite is exposed as a `dspy.Evaluate`
program, so end-to-end success is a first-class DSPy metric, not just the proxy.

```bash
# whole Ubuntu suite against a spawned VM (compiled policy auto-loaded)
control/.venv/bin/python control/evals.py --target ubuntu
control/.venv/bin/python control/evals.py --target ubuntu --scenario webmail,signup
```

`bootstrap_rollouts.py` closes the loop: it runs the suite and harvests each step
of every **passing** run as a labeled demo, which folds back into `optimize.py`'s
trainset. The cycle is **measure → harvest wins → compile → measure again**. Full
details, flags, and how to add a scenario: **[docs/evals.md](docs/evals.md)**.

### Accessibility tree (`--a11y`)

`agent_dspy.py --a11y` adds an **accessibility tree** to each step — the on-screen
elements with names/roles/rects — plus a `click_element` tool to act on an
element by name. `ui_tree()` tags each element `clickable` (a rect is trusted
only if it has size, isn't a bogus `(0,0)`, and is on-screen); when an element
isn't clickable, the agent **falls back** to vision (`left_click` on the
screenshot), keyboard, or shell. Works on both targets:

| | backend | in-guest helper | how it runs |
|---|---|---|---|
| **Ubuntu** | AT-SPI2 (`pyatspi`) | `config/ubuntu/atspi_helper.py` | SSH in the session |
| **Windows** | UI Automation (.NET) | `config/win11/uia_helper.ps1` | scheduled task, interactive token |

VM methods: `LinuxVM`/`WinVM.ensure_a11y()` / `ui_tree()` / `click_element()`.
(Windows UIA can't be queried from the SSH session — it's a different session —
so the helper runs in the **interactive desktop session** via a one-shot
scheduled task; Linux just borrows the session's DBus/X env.)

**What the prototype showed (honest):**
- **Observability is great on both** — `ui_tree()` reliably enumerates elements
  by name (the agent *knows* "Files", "File Explorer pinned", … exist).
- **Windows UIA gives reliable rects** — all 60 taskbar/app elements came back
  `clickable=True` with accurate coordinates; `click_element` takes the precise
  `rect` path. This is the a11y win that pays off.
- **Linux GTK4/libadwaita is weak** — GNOME Files/Settings report **bogus
  `(0,0)` rects** *and* no "activate/open" action on folders. There the fallback
  kicks in (vision/shell); the guide recommends `nautilus ~/Documents` / `ctrl-l`.

**Answer to "do a11y trees help complex tasks?":** yes — strongly on **Windows
(UIA)** where rects are dependable, and on Linux for **perception + well-behaved
widgets** (shell/GTK3), with graceful fallback to vision/shell where AT-SPI is
too immature (GTK4). a11y is opt-in (`--a11y`); default behavior is unchanged.

## Fast VM spawning (golden images)

A full install is slow (~15–25 min) and you only need to pay it once. **Bake** a
provisioned VM into a read-only base image, then **spawn** fresh VMs from it as
copy-on-write overlays — created in milliseconds, booted in ~30s.

```bash
# 1. Bake once (after install + provisioning), VM powered off:
./ubuntu.sh bake          # → vms/ubuntu-base.qcow2 (read-only) + base NVRAM
./win11.sh  bake

# 2. Spawn instances in seconds (each gets its own overlay/NVRAM/TPM/SSH port):
./spawn.sh ubuntu test1   # prints its SSH port + QMP socket
./spawn.sh ubuntu test2
./spawn.sh win11  qa1

# 3. Reset an instance to clean = delete its overlay:
rm vms/ubuntu/clones/test1.qcow2
```

Each overlay starts at ~200 KB and only stores its diffs from the base. Point
the agent at an instance with its printed `VM_SSH_PORT` / `VM_QMP_SOCK` (or the
`.env` vars). For running **many clones at once**, generalize first (regenerate
hostname / machine-id / SSH host keys; `sysprep` on Windows) — see
`docs/golden-images.md`. Design notes and the autoinstall gotchas live there too.

## Tuning

Override resources with env vars, e.g.:

```bash
RAM=12G CPUS=8 ./win11.sh
```

### Run headless (in the background, hands-free)

The agent never uses your real mouse/keyboard — QMP injects input into the VM's
*virtual* devices, and `screendump` reads the framebuffer directly. The only
reason you see activity is the QEMU window. Set `DISPLAY_MODE` to run with **no
window at all**, so a VM/agent works in the background while you keep using your
machine:

```bash
DISPLAY_MODE=none ./spawn.sh ubuntu work1     # headless — no window, full agent
DISPLAY_MODE=vnc  ./spawn.sh ubuntu work1     # headless but watchable via VNC
RAM=12G ./win11.sh                            # also honored by win11.sh / ubuntu.sh
```

- `gtk` (default) — shows a window on your desktop.
- `none` — **headless**: no window, runs in the background. Agent works unchanged
  (verified: `screendump` + SSH function with no display).
- `vnc` — headless but viewable: connect a VNC client to `127.0.0.1:5900`
  (`+VNC_DISPLAY`) to watch; it won't grab your input.

## Notes

- Networking is QEMU user-mode (NAT) — outbound internet works out of the box,
  no root needed. The host can't reach the VM by IP directly.
- Mouse is an absolute USB tablet, so the pointer tracks without grabbing.
- Release the keyboard/mouse grab (if any) with **Ctrl+Alt+G**.

## Contributing

Contributions are welcome — bug reports, docs, new scenarios, provider backends,
and OS-guide recipes. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and the PR
checklist, and please follow our [Code of Conduct](CODE_OF_CONDUCT.md). Found a
security issue? See [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © Ben Siewert
