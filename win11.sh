#!/usr/bin/env bash
# Run a Windows 11 VM.
#
#   ./win11.sh            normal boot (boots from disk)
#   ./win11.sh install    first-time install — fully unattended, hands-off
#   ./win11.sh purge      delete this VM's disk / firmware / TPM state
#
# First-time install needs the Windows 11 + virtio-win ISOs. Override paths with:
#   WIN_ISO=/path/to/Win11.iso VIRTIO_ISO=/path/to/virtio-win.iso ./win11.sh install
source "$(dirname "$0")/lib/common.sh"

NAME="win11"
VMD="$VM_DIR/$NAME"; mkdir -p "$VMD"   # all win11 state isolated under vms/win11/
DISK="$VMD/disk.qcow2"
VARS="$VMD/vars.fd"
TPMDIR="$VMD/tpm"
UNATTEND_ISO="$VMD/unattend.iso"
MON_SOCK="$VMD/qmp.sock"
AUTOUNATTEND="$PROJECT_DIR/config/autounattend.xml"

WIN_ISO="${WIN_ISO:-$ISO_DIR/Win11_25H2_English_x64_v2.iso}"
VIRTIO_ISO="${VIRTIO_ISO:-$ISO_DIR/virtio-win-0.1.285.iso}"

# Resources
RAM="${RAM:-8G}"
CPUS="${CPUS:-6}"
DISK_SIZE="${DISK_SIZE:-80G}"

# Purge: wipe this VM so the next `install` starts from a clean slate.
if [[ "${1:-}" == "purge" ]]; then
  pkill -f "qemu-system-x86_64 -name $NAME" 2>/dev/null || true
  echo ">> Purging $NAME VM state..."
  rm -rfv "$DISK" "$VARS" "$TPMDIR" "$UNATTEND_ISO" "$MON_SOCK"
  echo ">> Done. Run './win11.sh install' for a fresh install."
  exit 0
fi

# Bake the provisioned disk into a read-only golden base image for fast cloning.
if [[ "${1:-}" == "bake" ]]; then
  pgrep -f "qemu-system-x86_64 -name $NAME" >/dev/null && {
    echo "ERROR: $NAME VM is running — power it off before baking." >&2; exit 1; }
  bake_base "$DISK" "$VMD/base.qcow2" "$VARS" "$VMD/base-vars.fd"
  exit 0
fi

ensure_disk "$DISK" "$DISK_SIZE"
ensure_vars "$VARS"
start_swtpm "$TPMDIR"

MEDIA=()
BOOT=(-boot order=c)   # default: boot from hard disk
if [[ "${1:-}" == "install" ]]; then
  [[ -f "$WIN_ISO" ]]    || { echo "ERROR: Windows ISO not found: $WIN_ISO" >&2; exit 1; }
  [[ -f "$VIRTIO_ISO" ]] || { echo "ERROR: virtio-win ISO not found: $VIRTIO_ISO" >&2; exit 1; }
  build_unattend_iso "$AUTOUNATTEND" "$UNATTEND_ISO"
  # Reset UEFI NVRAM so stale boot entries (disk/PXE) don't take precedence
  # over the install CD.
  cp "$OVMF_VARS_TEMPLATE" "$VARS"
  echo ">> Unattended install — fully hands-off (boot key is auto-pressed)."
  echo "   Windows installs, provisions (Node.js, Git), and reboots to desktop."
  echo "   Login after install:  user / user"
  MEDIA=(
    -drive file="$WIN_ISO",media=cdrom,index=1,readonly=on
    -drive file="$VIRTIO_ISO",media=cdrom,index=2,readonly=on
    -drive file="$UNATTEND_ISO",media=cdrom,index=3,readonly=on
  )
  BOOT=(-boot order=d)
fi

rm -f "$MON_SOCK"

QEMU=(qemu-system-x86_64
  -name "$NAME"
  "${KVM_ARGS[@]}"
  -machine q35,smm=on
  -smp "$CPUS"
  -m "$RAM"
  -global driver=cfi.pflash01,property=secure,value=on
  -drive if=pflash,format=raw,unit=0,file="$OVMF_CODE",readonly=on
  -drive if=pflash,format=raw,unit=1,file="$VARS"
  $(tpm_args)
  -device virtio-scsi-pci,id=scsi0
  -device scsi-hd,drive=hd0,bus=scsi0.0
  -drive if=none,id=hd0,file="$DISK",format=qcow2,cache=writeback,discard=unmap
  "${MEDIA[@]}"
  "${BOOT[@]}"
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22
  -device virtio-net-pci,netdev=net0,romfile=
  -vga std
  -display gtk
  -usb -device usb-tablet
  -rtc base=localtime
  -qmp unix:"$MON_SOCK",server,nowait
)

if [[ "${1:-}" == "install" ]]; then
  # Run in the background so we can auto-tap a key past the one-time
  # "Press any key to boot from CD..." prompt — no manual timing needed.
  "${QEMU[@]}" &
  QEMU_PID=$!
  # Tap Enter every 0.3s for ~18s to clear the one-time "Press any key to
  # boot from CD..." prompt. Aggressive enough to never miss the ~5s window,
  # but stops well before Setup's GUI loads (~30s+) so it can't click buttons.
  python3 "$PROJECT_DIR/lib/qmp.py" "$MON_SOCK" autopress ret 60 0.3 &
  wait "$QEMU_PID"
else
  exec "${QEMU[@]}"
fi
