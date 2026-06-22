"""WinVM — full programmatic control of the QEMU Windows 11 VM from Python.

Two channels:
  * QMP  (host -> VM hardware): screenshot, mouse, keyboard. Works even at the
    login screen; needs nothing installed in the guest.
  * SSH  (into the guest OS): run commands, copy files. Needs OpenSSH running in
    the guest (provision.ps1 enables it) and the QEMU port-forward in win11.sh.

Example
-------
    from winvm import WinVM
    vm = WinVM()
    print(vm.powershell("node --version; git --version"))   # OS-level
    vm.screenshot("desktop.png")                              # visual
    vm.run("start notepad"); vm.sleep(2)
    vm.type("Hello from Python!")
"""
from __future__ import annotations

import base64
import json
import os
import socket
import time

_HERE = os.path.dirname(os.path.abspath(__file__))


class VM:
    """Base VM control: QMP (screen/keyboard/mouse) + SSH (run/copy).
    Subclasses set DEFAULT_QMP / DEFAULT_PORT and add OS-specific helpers
    (WinVM.powershell, LinuxVM.bash/sudo)."""
    DEFAULT_QMP = os.path.join(_HERE, "..", "vms", "win11", "qmp.sock")
    DEFAULT_PORT = 2222

    def __init__(
        self,
        qmp_sock: str | None = None,
        ssh_host: str | None = None,
        ssh_port: int | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        # Explicit args win; otherwise env (config.load_env), then subclass default.
        self.qmp_sock = os.path.abspath(qmp_sock or os.getenv("VM_QMP_SOCK") or self.DEFAULT_QMP)
        self.ssh_host = ssh_host or os.getenv("VM_SSH_HOST", "127.0.0.1")
        self.ssh_port = int(ssh_port or os.getenv("VM_SSH_PORT", str(self.DEFAULT_PORT)))
        self.username = username or os.getenv("VM_USER", "user")
        self.password = password or os.getenv("VM_PASS", "user")
        self._sock = None
        self._f = None
        self._ssh = None
        self._w = None
        self._h = None

    # ===================================================================== QMP
    def _qmp_connect(self):
        if self._sock is not None:
            return
        s = socket.socket(socket.AF_UNIX)
        s.connect(self.qmp_sock)
        f = s.makefile("rw")
        f.readline()  # greeting
        self._sock, self._f = s, f
        self._cmd({"execute": "qmp_capabilities"})

    def _cmd(self, obj: dict) -> dict:
        self._qmp_connect()
        self._f.write(json.dumps(obj) + "\n")
        self._f.flush()
        while True:                       # skip async events, return the reply
            line = self._f.readline()
            if not line:
                return {}
            msg = json.loads(line)
            if "event" in msg:
                continue
            return msg

    def screenshot(self, path: str | None = None):
        """Capture the screen to a PNG. Returns the file path (or a PIL.Image
        if Pillow is installed and no path is given)."""
        out = os.path.abspath(path) if path else os.path.join(_HERE, ".last.png")
        self._cmd({"execute": "screendump",
                   "arguments": {"filename": out, "format": "png"}})
        try:
            from PIL import Image
            img = Image.open(out)
            self._w, self._h = img.size
            if path:
                return out
            return img
        except ImportError:
            return out

    def _resolution(self):
        if self._w is None:
            self.screenshot(os.path.join(_HERE, ".size.png"))
        return self._w, self._h

    def _abs(self, x: int, y: int):
        w, h = self._resolution()
        return int(x / w * 32767), int(y / h * 32767)

    def move(self, x: int, y: int):
        ax, ay = self._abs(x, y)
        self._cmd({"execute": "input-send-event", "arguments": {"events": [
            {"type": "abs", "data": {"axis": "x", "value": ax}},
            {"type": "abs", "data": {"axis": "y", "value": ay}}]}})

    def click(self, x: int, y: int, button: str = "left", double: bool = False):
        self.move(x, y)
        time.sleep(0.05)
        for _ in range(2 if double else 1):
            for down in (True, False):
                self._cmd({"execute": "input-send-event", "arguments": {"events": [
                    {"type": "btn", "data": {"button": button, "down": down}}]}})
            time.sleep(0.03)

    def key(self, *qcodes: str):
        """Send one key chord, e.g. key('ctrl','c') or key('ret')."""
        keys = [{"type": "qcode", "data": k} for k in qcodes]
        self._cmd({"execute": "send-key", "arguments": {"keys": keys}})

    def type(self, text: str, delay: float = 0.03):
        for ch in text:
            mods, base = _char_to_qcode(ch)
            if base is None:
                continue
            keys = [{"type": "qcode", "data": m} for m in mods]
            keys.append({"type": "qcode", "data": base})
            self._cmd({"execute": "send-key", "arguments": {"keys": keys}})
            time.sleep(delay)

    def reset(self):
        self._cmd({"execute": "system_reset"})

    # ===================================================================== SSH
    def _ssh_connect(self, retries: int = 10, delay: float = 6.0):
        if self._ssh is not None:
            return self._ssh
        import paramiko
        last = None
        for _ in range(retries):
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                c.connect(self.ssh_host, port=self.ssh_port,
                          username=self.username, password=self.password,
                          look_for_keys=False, allow_agent=False,
                          timeout=20, banner_timeout=60, auth_timeout=30)
                self._ssh = c
                return c
            except Exception as e:           # sshd not ready / VM busy — retry
                last = e
                time.sleep(delay)
        raise RuntimeError(f"SSH connect failed after {retries} tries: {last}")

    def run(self, command: str, timeout: int = 120):
        """Run a command via the guest's default shell (cmd.exe on Windows, bash
        on Linux). Returns (exit_code, stdout, stderr)."""
        c = self._ssh_connect()
        _in, out, err = c.exec_command(command, timeout=timeout)
        rc = out.channel.recv_exit_status()
        return rc, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")

    def upload(self, local: str, remote: str):
        """Copy a host file into the guest (remote uses forward slashes, e.g.
        'C:/Users/user/Desktop/x.txt')."""
        sftp = self._ssh_connect().open_sftp()
        sftp.put(local, remote)
        sftp.close()

    def download(self, remote: str, local: str):
        sftp = self._ssh_connect().open_sftp()
        sftp.get(remote, local)
        sftp.close()

    # ================================================================== helpers
    @staticmethod
    def sleep(seconds: float):
        time.sleep(seconds)

    def close(self):
        if self._ssh:
            self._ssh.close()
        if self._sock:
            self._sock.close()
        self._ssh = self._sock = self._f = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class WinVM(VM):
    """Windows 11 VM. SSH default shell is cmd.exe; use powershell() for PS."""
    DEFAULT_QMP = os.path.join(_HERE, "..", "vms", "win11", "qmp.sock")
    DEFAULT_PORT = 2222

    def powershell(self, script: str, timeout: int = 300):
        """Run a PowerShell script robustly (base64 -EncodedCommand, no quoting).
        Returns stdout (raises on non-zero exit)."""
        enc = base64.b64encode(script.encode("utf-16-le")).decode()
        rc, out, err = self.run(
            f"powershell -NoProfile -NonInteractive -EncodedCommand {enc}", timeout)
        if rc != 0:
            raise RuntimeError(f"powershell exit {rc}: {err or out}")
        return out


class LinuxVM(VM):
    """Ubuntu/Linux VM. SSH default shell is bash."""
    DEFAULT_QMP = os.path.join(_HERE, "..", "vms", "ubuntu", "qmp.sock")
    DEFAULT_PORT = 2223

    def bash(self, script: str, timeout: int = 300):
        """Run a bash script; returns stdout (raises on non-zero exit)."""
        rc, out, err = self.run(script, timeout)
        if rc != 0:
            raise RuntimeError(f"bash exit {rc}: {err or out}")
        return out

    def sudo(self, script: str, timeout: int = 300):
        """Run a bash script as root via sudo (password supplied over stdin)."""
        import shlex
        rc, out, err = self.run(
            f"echo {shlex.quote(self.password)} | sudo -S bash -c {shlex.quote(script)}",
            timeout)
        if rc != 0:
            raise RuntimeError(f"sudo exit {rc}: {err or out}")
        return out

    def launch_gui(self, command: str):
        """Launch a GUI app into the logged-in desktop session from SSH by
        borrowing the session's DISPLAY/XAUTHORITY (Xorg)."""
        return self.run(
            "PID=$(pgrep -u %s gnome-shell | head -1); "
            "export $(tr '\\0' '\\n' < /proc/$PID/environ | "
            "grep -E '^(DISPLAY|XAUTHORITY|DBUS_SESSION_BUS_ADDRESS)=' | xargs); "
            "nohup %s >/dev/null 2>&1 & echo launched" % (self.username, command))


# --- character -> (modifiers, qcode) map for type() --------------------------
_BASE = {
    " ": "spc", "-": "minus", "=": "equal", "[": "bracket_left",
    "]": "bracket_right", "\\": "backslash", ";": "semicolon",
    "'": "apostrophe", "`": "grave_accent", ",": "comma", ".": "dot",
    "/": "slash", "\n": "ret", "\t": "tab",
}
_SHIFT = {
    "~": "grave_accent", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0", "_": "minus",
    "+": "equal", "{": "bracket_left", "}": "bracket_right", "|": "backslash",
    ":": "semicolon", '"': "apostrophe", "<": "comma", ">": "dot", "?": "slash",
}


def _char_to_qcode(ch: str):
    if ch.isalpha():
        return (["shift"] if ch.isupper() else []), ch.lower()
    if ch.isdigit():
        return [], ch
    if ch in _BASE:
        return [], _BASE[ch]
    if ch in _SHIFT:
        return ["shift"], _SHIFT[ch]
    return [], None
