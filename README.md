# QEMU VMs — Windows 11 & Ubuntu Desktop

Simple QEMU/KVM setup to run a Windows 11 VM and an Ubuntu Desktop VM.
Each VM is a single script. Disks, UEFI vars, and TPM state live in `vms/`.

## What's included

| File              | Purpose                                              |
|-------------------|------------------------------------------------------|
| `win11.sh`        | Run / install the Windows 11 VM (UEFI + TPM 2.0)     |
| `ubuntu.sh`       | Run / install the Ubuntu Desktop VM                  |
| `lib/common.sh`   | Shared config (paths, KVM, disk, UEFI, swtpm)        |
| `isos/`           | Installer ISOs (git-ignored)                         |
| `vms/`            | Auto-created: disks, firmware vars, TPM state        |

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

## Windows 11 install notes

Windows 11's setup won't see the fast `virtio` disk until you load its driver:

1. At "Where do you want to install Windows?", click **Load driver**.
2. Browse the second CD drive (virtio-win) → `vioscsi\w11\amd64` → OK.
3. The disk appears; continue the install.

After Windows is up, open the virtio CD and run `virtio-win-guest-tools.exe`
to install the network, display, and balloon drivers.

To skip the Microsoft-account requirement during setup: at the network step
press **Shift+F10**, run `OOBE\BYPASSNRO`, reboot, then choose "I don't have
internet". (Network works once virtio drivers are installed.)

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
