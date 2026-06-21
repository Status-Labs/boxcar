#!/usr/bin/env bash
# Run a Windows 11 VM.
#
#   ./win11.sh            normal boot (boots from disk)
#   ./win11.sh install    first-time install (boots from the Windows ISO)
#
# First-time install needs the Windows 11 + virtio-win ISOs. Override paths with:
#   WIN_ISO=/path/to/Win11.iso VIRTIO_ISO=/path/to/virtio-win.iso ./win11.sh install
source "$(dirname "$0")/lib/common.sh"

NAME="win11"
DISK="$VM_DIR/$NAME.qcow2"
VARS="$VM_DIR/$NAME-vars.fd"
TPMDIR="$VM_DIR/$NAME-tpm"

WIN_ISO="${WIN_ISO:-$ISO_DIR/Win11_25H2_English_x64_v2.iso}"
VIRTIO_ISO="${VIRTIO_ISO:-$ISO_DIR/virtio-win-0.1.285.iso}"

# Resources
RAM="${RAM:-8G}"
CPUS="${CPUS:-6}"
DISK_SIZE="${DISK_SIZE:-80G}"

ensure_disk "$DISK" "$DISK_SIZE"
ensure_vars "$VARS"
start_swtpm "$TPMDIR"

MEDIA=()
BOOT=(-boot order=c)   # default: boot from hard disk
if [[ "${1:-}" == "install" ]]; then
  [[ -f "$WIN_ISO" ]]    || { echo "ERROR: Windows ISO not found: $WIN_ISO" >&2; exit 1; }
  [[ -f "$VIRTIO_ISO" ]] || { echo "ERROR: virtio-win ISO not found: $VIRTIO_ISO" >&2; exit 1; }
  echo ">> Install mode: booting from $WIN_ISO"
  echo "   During setup, click 'Load driver' -> browse the virtio CD ->"
  echo "   vioscsi\\w11\\amd64 (disk) so Windows can see the virtio disk."
  MEDIA=(
    -drive file="$WIN_ISO",media=cdrom,index=1,readonly=on
    -drive file="$VIRTIO_ISO",media=cdrom,index=2,readonly=on
  )
  BOOT=(-boot menu=on,order=d)
fi

exec qemu-system-x86_64 \
  -name "$NAME" \
  "${KVM_ARGS[@]}" \
  -machine q35,smm=on \
  -smp "$CPUS" \
  -m "$RAM" \
  -global driver=cfi.pflash01,property=secure,value=on \
  -drive if=pflash,format=raw,unit=0,file="$OVMF_CODE",readonly=on \
  -drive if=pflash,format=raw,unit=1,file="$VARS" \
  $(tpm_args) \
  -device virtio-scsi-pci,id=scsi0 \
  -device scsi-hd,drive=hd0,bus=scsi0.0 \
  -drive if=none,id=hd0,file="$DISK",format=qcow2,cache=writeback,discard=unmap \
  "${MEDIA[@]}" \
  "${BOOT[@]}" \
  -netdev user,id=net0 \
  -device virtio-net-pci,netdev=net0 \
  -vga std \
  -display gtk \
  -usb -device usb-tablet \
  -rtc base=localtime
