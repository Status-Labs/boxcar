#!/usr/bin/env bash
# Spawn a fresh VM from a baked golden image — in seconds, no install.
#
#   ./spawn.sh <win11|ubuntu> <instance-name>
#
# Creates a copy-on-write overlay on vms/<type>-base.qcow2 plus its own firmware
# NVRAM, TPM (Windows), QMP socket and SSH port-forward, then boots it. The base
# stays read-only, so deleting the overlay resets the instance to clean.
#
# Bake a base first:  ./win11.sh bake   /   ./ubuntu.sh bake
source "$(dirname "$0")/lib/common.sh"

TYPE="${1:-}"; INSTANCE="${2:-}"
case "$TYPE" in win11|ubuntu) ;; *)
  echo "usage: ./spawn.sh <win11|ubuntu> <instance-name>" >&2; exit 1;; esac
[[ -n "$INSTANCE" ]] || { echo "usage: ./spawn.sh $TYPE <instance-name>" >&2; exit 1; }

BASE="$VM_DIR/$TYPE/base.qcow2"
BASE_VARS="$VM_DIR/$TYPE/base-vars.fd"
[[ -f "$BASE" ]] || { echo "ERROR: no base image: $BASE — run ./$TYPE.sh bake first" >&2; exit 1; }

CLONES="$VM_DIR/$TYPE/clones"; mkdir -p "$CLONES"
NAME="$TYPE-$INSTANCE"
DISK="$CLONES/$INSTANCE.qcow2"
VARS="$CLONES/$INSTANCE-vars.fd"
TPMDIR="$CLONES/$INSTANCE-tpm"
MON_SOCK="$CLONES/$INSTANCE-qmp.sock"

RAM="${RAM:-6G}"
CPUS="${CPUS:-4}"

# Copy-on-write overlay on the read-only base (instant; starts at a few KB).
if [[ ! -f "$DISK" ]]; then
  echo ">> Creating overlay $DISK on $(basename "$BASE")"
  qemu-img create -f qcow2 -F qcow2 -b "$(readlink -f "$BASE")" "$DISK" >/dev/null
fi
if [[ ! -f "$VARS" ]]; then cp "$BASE_VARS" "$VARS"; chmod u+w "$VARS"; fi  # base-vars is read-only

# Pick a free host port for SSH forwarding (2222, 2223, ...).
port=2222
while ss -Hltn "sport = :$port" 2>/dev/null | grep -q . ; do port=$((port+1)); done

rm -f "$MON_SOCK"
COMMON=(
  -name "$NAME"
  "${KVM_ARGS[@]}"
  -smp "$CPUS" -m "$RAM"
  -drive if=none,id=hd0,file="$DISK",format=qcow2,cache=writeback,discard=unmap
  -device virtio-scsi-pci,id=scsi0 -device scsi-hd,drive=hd0,bus=scsi0.0
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:"$port"-:22
  -device virtio-net-pci,netdev=net0,romfile=
  -vga std "${DISPLAY_ARGS[@]}" -usb -device usb-tablet
  -qmp unix:"$MON_SOCK",server,nowait
)

if [[ "$TYPE" == "win11" ]]; then
  start_swtpm "$TPMDIR"
  # tpm_args prints space-separated flags we intend to word-split into the array.
  # shellcheck disable=SC2207
  QEMU=(qemu-system-x86_64 -machine q35,smm=on
    -global driver=cfi.pflash01,property=secure,value=on
    -drive if=pflash,format=raw,unit=0,file="$OVMF_CODE",readonly=on
    -drive if=pflash,format=raw,unit=1,file="$VARS"
    $(tpm_args) -rtc base=localtime "${COMMON[@]}")
else  # ubuntu — plain (non-Secure-Boot) UEFI, no TPM
  QEMU=(qemu-system-x86_64 -machine q35
    -drive if=pflash,format=raw,unit=0,file=/usr/share/OVMF/OVMF_CODE_4M.fd,readonly=on
    -drive if=pflash,format=raw,unit=1,file="$VARS"
    -rtc base=utc "${COMMON[@]}")
fi

echo ">> Spawned '$NAME'"
echo "   SSH:  ssh -p $port user@127.0.0.1   (password: user)"
echo "   QMP:  $MON_SOCK"
echo "   Agent: VM_SSH_PORT=$port VM_QMP_SOCK=$MON_SOCK ..."
echo "   Reset: delete $DISK (recreated from base on next spawn)"
"${QEMU[@]}"
