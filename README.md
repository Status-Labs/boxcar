# QEMU VMs — Windows 11 & Ubuntu Desktop

Simple QEMU/KVM setup to run a Windows 11 VM and an Ubuntu Desktop VM.
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
| `control/agent_graph.py`| Same agent as a LangGraph StateGraph            |
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

### LangGraph variant (`control/agent_graph.py`)

Same tools, same `WinVM` execution, same `.env` — but the loop is an explicit
**LangGraph `StateGraph`** (`START → llm → act → llm → … → END`) using
LangChain's `init_chat_model`, so it plugs into the LangChain/LangGraph
ecosystem (checkpointers, streaming, tracing, human-in-the-loop). The screenshot
result is fed back as an image message so any vision model can see the desktop.

```bash
cp .env.example .env        # same config as agent.py
.venv/bin/python agent_graph.py "Open Notepad and write a haiku"
.venv/bin/python agent_graph.py --provider openai "..."
```

`agent.py` is the lightweight, dependency-minimal option (provider SDKs only);
`agent_graph.py` adds the LangGraph/LangChain stack (in `requirements.txt`).

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

## Notes

- Networking is QEMU user-mode (NAT) — outbound internet works out of the box,
  no root needed. The host can't reach the VM by IP directly.
- Mouse is an absolute USB tablet, so the pointer tracks without grabbing.
- Release the keyboard/mouse grab (if any) with **Ctrl+Alt+G**.
