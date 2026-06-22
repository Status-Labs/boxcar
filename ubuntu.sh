#!/usr/bin/env bash
# Run an Ubuntu Desktop VM.
#
#   ./ubuntu.sh           normal boot (boots from disk)
#   ./ubuntu.sh install   fully automated autoinstall (Node.js + Chrome + SSH)
#   ./ubuntu.sh purge     delete this VM's disk / firmware state
#
# Install is unattended via Ubuntu autoinstall (cloud-init): it boots the ISO's
# kernel directly with `autoinstall`, seeds the config from a NoCloud CIDATA
# disk, installs Ubuntu Desktop, then runs config/ubuntu/provision.sh in the
# target (Node.js LTS, Google Chrome, OpenSSH, autologin, no screen lock).
# Login after install: user / user
source "$(dirname "$0")/lib/common.sh"

NAME="ubuntu"
VMD="$VM_DIR/$NAME"; mkdir -p "$VMD"   # all ubuntu state isolated under vms/ubuntu/
DISK="$VMD/disk.qcow2"
VARS="$VMD/vars.fd"
MON_SOCK="$VMD/qmp.sock"
KERNEL="$VMD/vmlinuz"
INITRD="$VMD/initrd"
SEED="$VMD/seed.iso"

UBUNTU_ISO="${UBUNTU_ISO:-$ISO_DIR/ubuntu-24.04.4-desktop-amd64.iso}"
USERDATA_TMPL="$PROJECT_DIR/config/ubuntu/user-data.tmpl"
PROVISION="$PROJECT_DIR/config/ubuntu/provision.sh"

# Plain (non-Secure-Boot) UEFI firmware — required so QEMU's -kernel direct boot
# of the installer isn't blocked by Secure Boot. Ubuntu doesn't need SB.
OVMF_CODE_NB="/usr/share/OVMF/OVMF_CODE_4M.fd"
OVMF_VARS_NB="/usr/share/OVMF/OVMF_VARS_4M.fd"

RAM="${RAM:-8G}"
CPUS="${CPUS:-6}"
DISK_SIZE="${DISK_SIZE:-64G}"

if [[ "${1:-}" == "purge" ]]; then
  pkill -f "qemu-system-x86_64 -name $NAME" 2>/dev/null || true
  echo ">> Purging $NAME VM state..."
  rm -rfv "$DISK" "$VARS" "$MON_SOCK" "$KERNEL" "$INITRD" "$SEED"
  echo ">> Done. Run './ubuntu.sh install' for a fresh install."
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
[[ -f "$VARS" ]] || cp "$OVMF_VARS_NB" "$VARS"

rm -f "$MON_SOCK"
INSTALL_ARGS=()
if [[ "${1:-}" == "install" ]]; then
  [[ -f "$UBUNTU_ISO" ]] || { echo "ERROR: Ubuntu ISO not found: $UBUNTU_ISO" >&2; exit 1; }
  need xorriso

  # Extract the installer kernel + initrd once (cached in vms/).
  if [[ ! -f "$KERNEL" || ! -f "$INITRD" ]]; then
    echo ">> Extracting installer kernel/initrd from ISO..."
    rm -f "$KERNEL" "$INITRD"
    xorriso -osirrox on -indev "$UBUNTU_ISO" \
      -extract /casper/vmlinuz "$KERNEL" \
      -extract /casper/initrd "$INITRD" 2>/dev/null
  fi

  # Build the NoCloud seed (CIDATA) with provision.sh base64-injected.
  echo ">> Building autoinstall seed..."
  b64="$(base64 -w0 "$PROVISION")"
  staging="$(mktemp -d)"
  sed "s#__PROVISION_B64__#${b64}#" "$USERDATA_TMPL" > "$staging/user-data"
  printf 'instance-id: ubuntu-vm\nlocal-hostname: ubuntu-vm\n' > "$staging/meta-data"
  rm -f "$SEED"
  xorriso -as mkisofs -V CIDATA -J -r -o "$SEED" "$staging" >/dev/null 2>&1
  rm -rf "$staging"

  # Fresh disk + firmware vars for a clean install.
  rm -f "$DISK"; ensure_disk "$DISK" "$DISK_SIZE"
  cp "$OVMF_VARS_NB" "$VARS"

  echo ">> Unattended Ubuntu autoinstall — hands-off (~15-20 min)."
  echo "   Login after install:  user / user"
  INSTALL_ARGS=(
    -kernel "$KERNEL"
    -initrd "$INITRD"
    -append "autoinstall ds=nocloud ---"
    -drive file="$UBUNTU_ISO",media=cdrom,index=1,readonly=on
    -drive file="$SEED",media=cdrom,index=2,readonly=on
    -no-reboot               # exit (don't loop the installer) when install ends
  )
fi

QEMU=(qemu-system-x86_64
  -name "$NAME"
  "${KVM_ARGS[@]}"
  -machine q35
  -smp "$CPUS"
  -m "$RAM"
  -drive if=pflash,format=raw,unit=0,file="$OVMF_CODE_NB",readonly=on
  -drive if=pflash,format=raw,unit=1,file="$VARS"
  -device virtio-scsi-pci,id=scsi0
  -device scsi-hd,drive=hd0,bus=scsi0.0
  -drive if=none,id=hd0,file="$DISK",format=qcow2,cache=writeback,discard=unmap
  "${INSTALL_ARGS[@]}"
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:2223-:22
  -device virtio-net-pci,netdev=net0
  -vga std
  -display gtk
  -usb -device usb-tablet
  -rtc base=utc
  -qmp unix:"$MON_SOCK",server,nowait
)

exec "${QEMU[@]}"
