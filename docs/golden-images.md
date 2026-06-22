# Plan: golden images + fast VM spawning

## Problem
A full install is slow and paid **every** `purge → install`:

| VM | Full install time |
|----|------|
| Windows 11 | ~15–25 min |
| Ubuntu Desktop (autoinstall) | ~15–25 min |

We want to pay that **once**, then spawn fresh, already-provisioned VMs in seconds.

## Approach: bake a base image, spawn copy-on-write overlays
qcow2 supports **backing files**: a new disk can be a thin overlay on a
read-only base, storing only its diffs.

```
             vms/win11/base.qcow2   (read-only "golden": OS + Node + Chrome + SSH)
                  ▲        ▲        ▲
   overlay-a.qcow2   overlay-b.qcow2   overlay-c.qcow2   (each created in <1s, starts ~KB)
```

Create an overlay (instant):
```bash
qemu-img create -f qcow2 -F qcow2 -b vms/win11/base.qcow2 vms/win11/clones/a.qcow2
```
Boot the overlay → only the OS boot (~20–40s), no install. Base stays pristine,
so **reset = delete overlay, recreate from base** (instant).

## Per-instance state (besides the disk overlay)
Each spawned VM also needs its own:
- **UEFI NVRAM vars** — `cp` the base/template vars per instance
- **TPM state dir** (Windows only) — fresh swtpm state per instance
- **QMP control socket** — `vms/<instance>-qmp.sock`
- **SSH host-forward port** — allocate a free port (2222, 2223, 2224, …)
- **Name** — unique `-name <instance>` so pgrep/QMP target the right VM

## Proposed implementation
1. **`bake` command** (add to `win11.sh` / `ubuntu.sh`):
   - after a successful install, copy/promote `vms/<name>.qcow2` →
     `vms/<name>-base.qcow2` and mark it read-only (`chmod -w`).
   - (optional) run a light "generalize" pass first — see caveat below.
2. **`spawn.sh <win11|ubuntu> <instance>`**:
   - `qemu-img create` an overlay on the base into `vms/<type>/clones/`
   - copy NVRAM vars, init TPM (win), pick a free SSH port, set a QMP socket
   - boot it; print the SSH port + QMP socket so the agent can attach
3. **`WinVM`/agent** already take `qmp_sock`, `ssh_port` args → point them at the
   spawned instance's socket/port (or via `.env` `VM_*` vars).

## Caveat: generalization (only for *parallel* clones)
Running several clones **at once** means duplicate identity:
- hostname, machine-id (Linux) / machine SID (Windows), SSH host keys.

Fixes:
- **Ubuntu:** truncate `/etc/machine-id`, remove SSH host keys, set hostname on
  first boot (cloud-init or a oneshot service). Cheap.
- **Windows:** `sysprep /generalize /oobe` before baking (heavier; regenerates
  SID, prompts minimal OOBE on first boot). Or accept duplicates for isolated,
  non-domain dev VMs.

For **sequential / revert-to-clean** use (one VM at a time), generalization is
unnecessary — duplicates never coexist.

## Alternative considered
- **qcow2 internal snapshots** (`qemu-img snapshot -c/-a`): good for
  save/restore of a single VM, but backing-file overlays are better for spawning
  *many* independent VMs. Use snapshots for "checkpoint this VM", overlays for
  "give me N fresh VMs".

## Status
- [x] Ubuntu desktop autoinstall working (Node + Chrome + SSH + encrypted keyring).
- [x] `bake` added to `win11.sh` and `ubuntu.sh` (`bake_base` in `lib/common.sh`).
- [x] `spawn.sh` — CoW overlay + per-instance NVRAM/TPM/QMP/SSH-port, boots in seconds.
- [x] Ubuntu base baked (~5.5G) and verified: spawn = overlay in ~5ms, boot ~30s, overlay ~15M.
- [x] Bake the Windows base (`./win11.sh bake`) → 29G, spawn+boot verified.
- [ ] Optional: first-boot generalization for parallel fleets.
- [ ] Optional: slim the Windows base (disk cleanup + zero free space before bake).

### Measured
| Step | Cost |
|------|------|
| Bake Ubuntu base (one-time, compressed) | ~3.5 min → 5.5G read-only |
| Spawn overlay creation | ~5 ms (200 KB) |
| Spawn boot to login | ~30 s |
| Overlay after first boot | ~15 MB (diffs only) |

---

## Appendix: Ubuntu autoinstall lessons (so we don't relearn them)
- **Trigger:** boot `casper/vmlinuz`+`casper/initrd` directly via QEMU
  `-kernel`/`-initrd` with `-append "autoinstall ds=nocloud ---"` + a NoCloud
  seed ISO labeled `CIDATA` (user-data + meta-data). Avoids GRUB keypress hacks.
- **Secure Boot off** for the install: a direct `-kernel` boot is blocked by SB,
  so use plain `OVMF_CODE_4M.fd` / `OVMF_VARS_4M.fd` (not the `.ms` variant).
- **`-no-reboot`** in install mode: otherwise `-kernel` re-runs the installer in
  a loop. (autoinstall reboots at end → QEMU exits instead.)
- **Display:** `virtio-vga-gl` + `gl=on` breaks QMP `screendump` ("no surface").
  Use `-vga std` so screenshots (and the agent) work.
- **`curl` is NOT in the base desktop target** — `late-commands` that use curl
  fail with exit 127, and the desktop installer treats a failing late-command as
  a **fatal crash**. Fix: install `curl ca-certificates gnupg` first (autoinstall
  `packages:`), and wrap provisioning with `|| true` + log to
  `/var/log/provision.log` so provisioning can never crash the install.
