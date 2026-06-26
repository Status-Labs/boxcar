# Shared QEMU helpers and config. Sourced by win11.sh and ubuntu.sh.
# Not meant to be run directly.
# shellcheck shell=bash
# These vars are consumed by the scripts that source this file, so shellcheck
# can't see their use from here:
# shellcheck disable=SC2034

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

# --- Display mode ------------------------------------------------------------
# DISPLAY_MODE=gtk  (default) — show a QEMU window on your desktop.
#             =none           — HEADLESS: no window, runs fully in the background.
#                               The agent still works (QMP screendump reads the
#                               framebuffer; QMP input goes to the VM's *virtual*
#                               mouse/keyboard — never your real ones). Use this
#                               to keep using your own mouse/screen while it runs.
#             =vnc            — headless but viewable: connect a VNC client to
#                               127.0.0.1:5900+VNC_DISPLAY to watch, no input grab.
case "${DISPLAY_MODE:-gtk}" in
  none) DISPLAY_ARGS=(-display none) ;;
  vnc)  DISPLAY_ARGS=(-vnc "127.0.0.1:${VNC_DISPLAY:-0}") ;;
  gtk)  DISPLAY_ARGS=(-display gtk) ;;
  *)    echo "WARNING: unknown DISPLAY_MODE='$DISPLAY_MODE', using gtk." >&2
        DISPLAY_ARGS=(-display gtk) ;;
esac

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

# --- Golden image baking ------------------------------------------------------
# bake_base <disk> <base> <vars> <base-vars>
# Flatten+compress the provisioned disk into a read-only base image, and stash a
# copy of the firmware NVRAM as the template clones boot from. Spawn fast VMs
# from the base via copy-on-write overlays (see spawn.sh).
bake_base() {
  local disk="$1" base="$2" vars="$3" base_vars="$4"
  [[ -f "$disk" ]] || { echo "ERROR: nothing to bake — no disk at $disk" >&2; exit 1; }
  echo ">> Baking base image (flatten + compress)..."
  rm -f "$base"
  qemu-img convert -O qcow2 -c "$disk" "$base"
  chmod 0444 "$base"
  # rm -f first: $base_vars from a previous bake is 0444, so a plain cp onto it
  # fails with "Permission denied" (the disk above avoids this via its own rm -f).
  [[ -f "$vars" ]] && { rm -f "$base_vars"; cp "$vars" "$base_vars"; chmod 0444 "$base_vars"; }
  echo ">> Base ready: $base ($(du -h "$base" | cut -f1), read-only)."
  echo "   Spawn instances with:  ./spawn.sh <win11|ubuntu> <name>"
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

# --- Unattend ISO ------------------------------------------------------------
# build_unattend_iso <answer-file> <out.iso>  — a tiny CD holding autounattend.xml
# (and provision.ps1, if present alongside it) at its root, which Windows Setup
# auto-detects on removable media.
build_unattend_iso() {
  local answer="$1" out="$2"
  need xorriso
  [[ -f "$answer" ]] || { echo "ERROR: answer file not found: $answer" >&2; exit 1; }
  local srcdir; srcdir="$(dirname "$answer")"
  local provision="$srcdir/provision.ps1"
  if [[ ! -f "$out" || "$answer" -nt "$out" || ( -f "$provision" && "$provision" -nt "$out" ) ]]; then
    echo ">> Building unattend ISO: $out"
    local staging; staging="$(mktemp -d)"
    cp "$answer" "$staging/autounattend.xml"
    [[ -f "$provision" ]] && cp "$provision" "$staging/provision.ps1"
    xorriso -as mkisofs -J -r -V UNATTEND -o "$out" "$staging" >/dev/null 2>&1
    rm -rf "$staging"
  fi
}

# --- TPM device args ---------------------------------------------------------
tpm_args() {
  echo "-chardev socket,id=chrtpm,path=$TPM_SOCK -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-crb,tpmdev=tpm0"
}
