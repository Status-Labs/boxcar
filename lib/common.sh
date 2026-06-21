# Shared QEMU helpers and config. Sourced by win11.sh and ubuntu.sh.
# Not meant to be run directly.

set -euo pipefail

# --- Paths -------------------------------------------------------------------
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_DIR="$PROJECT_DIR/vms"           # disks, UEFI vars, TPM state live here
ISO_DIR="${ISO_DIR:-$PROJECT_DIR/isos}"   # installer ISOs (git-ignored)

# Firmware: UEFI + Secure Boot (Microsoft keys enrolled) — required by Win 11.
OVMF_CODE="/usr/share/OVMF/OVMF_CODE_4M.ms.fd"
OVMF_VARS_TEMPLATE="/usr/share/OVMF/OVMF_VARS_4M.ms.fd"

mkdir -p "$VM_DIR"

# --- Preflight ---------------------------------------------------------------
need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not found. Install it first." >&2; exit 1; }; }
need qemu-system-x86_64
need qemu-img

KVM_ARGS=()
if [[ -r /dev/kvm && -w /dev/kvm ]]; then
  KVM_ARGS=(-enable-kvm -cpu host)
else
  echo "WARNING: no /dev/kvm access — falling back to slow emulation." >&2
  KVM_ARGS=(-cpu max)
fi

# --- Disk --------------------------------------------------------------------
# ensure_disk <path> <size>  — create a qcow2 disk if it doesn't exist.
ensure_disk() {
  local disk="$1" size="$2"
  if [[ ! -f "$disk" ]]; then
    echo ">> Creating $size disk: $disk"
    qemu-img create -f qcow2 "$disk" "$size" >/dev/null
  fi
}

# --- UEFI vars (per-VM writable copy of the firmware NVRAM) -------------------
# ensure_vars <path>
ensure_vars() {
  local vars="$1"
  if [[ ! -f "$vars" ]]; then
    echo ">> Initialising UEFI vars: $vars"
    cp "$OVMF_VARS_TEMPLATE" "$vars"
  fi
}

# --- Software TPM 2.0 (required by Win 11; harmless for Ubuntu) ---------------
# Starts swtpm in the background and returns its socket path via $TPM_SOCK.
# The swtpm process is killed automatically when this script exits.
TPM_PID=""
start_swtpm() {
  local statedir="$1"
  need swtpm
  mkdir -p "$statedir"
  TPM_SOCK="$statedir/swtpm-sock"
  swtpm socket \
    --tpmstate dir="$statedir" \
    --ctrl type=unixio,path="$TPM_SOCK" \
    --tpm2 \
    --daemon \
    --pid file="$statedir/swtpm.pid"
  TPM_PID="$(cat "$statedir/swtpm.pid")"
  trap 'cleanup' EXIT
}

cleanup() {
  [[ -n "$TPM_PID" ]] && kill "$TPM_PID" 2>/dev/null || true
}

# --- TPM device args ---------------------------------------------------------
tpm_args() {
  echo "-chardev socket,id=chrtpm,path=$TPM_SOCK -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-crb,tpmdev=tpm0"
}
