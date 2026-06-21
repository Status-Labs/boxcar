#!/usr/bin/env bash
# Run an Ubuntu Desktop VM.
#
#   ./ubuntu.sh           normal boot (boots from disk)
#   ./ubuntu.sh install   first-time install (boots from the Ubuntu ISO)
#
# Override the ISO with: UBUNTU_ISO=/path/to/ubuntu.iso ./ubuntu.sh install
source "$(dirname "$0")/lib/common.sh"

NAME="ubuntu"
DISK="$VM_DIR/$NAME.qcow2"
VARS="$VM_DIR/$NAME-vars.fd"
TPMDIR="$VM_DIR/$NAME-tpm"

UBUNTU_ISO="${UBUNTU_ISO:-$ISO_DIR/ubuntu-24.04.4-desktop-amd64.iso}"

# Resources
RAM="${RAM:-8G}"
CPUS="${CPUS:-6}"
DISK_SIZE="${DISK_SIZE:-64G}"

ensure_disk "$DISK" "$DISK_SIZE"
ensure_vars "$VARS"
start_swtpm "$TPMDIR"

MEDIA=()
BOOT=(-boot order=c)
if [[ "${1:-}" == "install" ]]; then
  [[ -f "$UBUNTU_ISO" ]] || { echo "ERROR: Ubuntu ISO not found: $UBUNTU_ISO" >&2; exit 1; }
  echo ">> Install mode: booting from $UBUNTU_ISO"
  MEDIA=(-drive file="$UBUNTU_ISO",media=cdrom,index=1,readonly=on)
  BOOT=(-boot menu=on,order=d)
fi

exec qemu-system-x86_64 \
  -name "$NAME" \
  "${KVM_ARGS[@]}" \
  -machine q35 \
  -smp "$CPUS" \
  -m "$RAM" \
  -drive if=pflash,format=raw,unit=0,file="$OVMF_CODE",readonly=on \
  -drive if=pflash,format=raw,unit=1,file="$VARS" \
  -device virtio-scsi-pci,id=scsi0 \
  -device scsi-hd,drive=hd0,bus=scsi0.0 \
  -drive if=none,id=hd0,file="$DISK",format=qcow2,cache=writeback,discard=unmap \
  "${MEDIA[@]}" \
  "${BOOT[@]}" \
  -netdev user,id=net0 \
  -device virtio-net-pci,netdev=net0 \
  -device virtio-vga-gl \
  -display gtk,gl=on \
  -usb -device usb-tablet \
  -rtc base=utc
