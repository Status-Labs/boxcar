"""Programmatic control of a QEMU VM from Python — Windows or Ubuntu.

Two channels, both OS-agnostic at the transport level:
  * QMP  (host -> VM hardware): screenshot, mouse, keyboard. Works even at the
    login screen; needs nothing installed in the guest.
  * SSH  (into the guest OS): run commands, copy files. Needs OpenSSH in the
    guest (the provision scripts enable it) and the QEMU port-forward.

Class layout (the ONLY Windows-vs-Ubuntu differences live in the subclasses):
  * VM       — shared base: QMP (screenshot/click/key/type) + SSH (run/upload).
  * WinVM    — Windows 11: default port 2222 / vms/win11/qmp.sock; .powershell().
  * LinuxVM  — Ubuntu:     default port 2223 / vms/ubuntu/qmp.sock; .bash()/.sudo()/.launch_gui().

Example
-------
    from winvm import WinVM, LinuxVM
    win = WinVM();   print(win.powershell("node --version"))   # Windows
    ubu = LinuxVM(); print(ubu.bash("node --version"))         # Ubuntu
    win.screenshot("desktop.png"); win.click(100, 200); win.type("hi")
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


# ============================================================================
# OS-specific subclasses — Windows vs Ubuntu differences live ONLY below here.
# ============================================================================
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

    # --- Accessibility tree (UI Automation) ------------------------------------
    _UIA_LOCAL = os.path.join(_HERE, "..", "config", "win11", "uia_helper.ps1")

    def ensure_a11y(self):
        """Upload the UIA helper. (System.Windows.Automation is built into .NET on
        Windows — nothing to install.)"""
        self.upload(os.path.abspath(self._UIA_LOCAL),
                    f"C:/Users/{self.username}/uia_helper.ps1")

    def _uia_dump(self, limit: int = 80) -> str:
        """Run the UIA helper in the INTERACTIVE desktop session via a scheduled
        task (the SSH session is a different session and can't see the desktop),
        and return the JSON it writes to uia_out.json."""
        u = self.username
        outp = rf"C:\Users\{u}\uia_out.json"
        helper = rf"C:\Users\{u}\uia_helper.ps1"
        self.run(f'cmd /c del /q "{outp}" 2>nul')
        tr = (f"powershell -NoProfile -ExecutionPolicy Bypass -File {helper} {limit}")
        self.run(f'schtasks /create /tn uiaq /tr "{tr}" /sc once /st 00:00 '
                 f'/ru {u} /it /f')
        self.run("schtasks /run /tn uiaq")
        content = ""
        for _ in range(10):
            _rc, content, _e = self.run(f'cmd /c if exist "{outp}" type "{outp}"')
            if content.strip():
                break
            time.sleep(1.5)
        self.run("schtasks /delete /tn uiaq /f")
        return content.strip()

    def ui_tree(self, limit: int = 80):
        """Return visible, actionable UI elements as
        [{"name","role","rect":[x,y,w,h],"clickable":bool}] from Windows UIA.
        Windows reports reliable rects, so `clickable` is essentially always True."""
        raw = self._uia_dump(limit)
        try:
            data = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict):
            data = [data] if data.get("name") else []
        for e in data:
            r = e.get("rect")
            e["clickable"] = bool(r and r[2] > 0 and r[3] > 0
                                  and 0 <= r[0] < 6000 and 0 <= r[1] < 4000)
        return data

    def click_element(self, name=None, role=None, index=None, double=False):
        """Click a UI element by name or index using its UIA rect (reliable on
        Windows). Returns (ok: bool, how: str) — "rect" / "bogus" / "notfound"."""
        els = self.ui_tree(limit=400)  # exhaustive: resolve the rect even for
        target = None                  # deep cells the model-facing tree may cap
        if index is not None and 0 <= index < len(els):
            target = els[index]
        elif name:
            target = next((e for e in els
                           if name.lower() in (e["name"] or "").lower()
                           and (role is None or role == e["role"])), None)
        if target is None:
            return False, "notfound"
        if not target.get("clickable"):
            return False, "bogus"
        x, y, w, h = target["rect"]
        self.click(int(x + w / 2), int(y + h / 2), double=double)
        return True, "rect"


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

    def _session_env(self) -> str:
        """Shell prefix that exports the logged-in GNOME session's env (DISPLAY,
        XAUTHORITY, DBUS_SESSION_BUS_ADDRESS) so SSH commands can reach the GUI
        and the AT-SPI accessibility bus."""
        return (f"PID=$(pgrep -u {self.username} gnome-shell | head -1); "
                "export $(tr '\\0' '\\n' < /proc/$PID/environ | grep -E "
                "'^(DISPLAY|XAUTHORITY|DBUS_SESSION_BUS_ADDRESS)=' | xargs); ")

    def launch_gui(self, command: str):
        """Launch a GUI app into the logged-in desktop session from SSH."""
        return self.run(self._session_env() + f"nohup {command} >/dev/null 2>&1 & echo launched")

    # --- Accessibility tree (AT-SPI) -------------------------------------------
    _A11Y_REMOTE = "/tmp/atspi_helper.py"
    _A11Y_LOCAL = os.path.join(_HERE, "..", "config", "ubuntu", "atspi_helper.py")

    def ensure_a11y(self):
        """Install python3-pyatspi and turn on toolkit accessibility (idempotent).
        For golden images, bake this into provision.sh instead."""
        self.run("dpkg -s python3-pyatspi >/dev/null 2>&1 || "
                 f"(echo {self.password} | sudo -S apt-get install -y "
                 "python3-pyatspi >/dev/null 2>&1)", timeout=180)
        self.run(self._session_env() + "gsettings set "
                 "org.gnome.desktop.interface toolkit-accessibility true")
        self.upload(os.path.abspath(self._A11Y_LOCAL), self._A11Y_REMOTE)

    @staticmethod
    def _rect_clickable(r):
        """A rect is reliable to click only if it has size, isn't piled at the
        (0,0) origin (the GTK4 'bogus extents' tell), and is on-screen."""
        return bool(r and r[2] > 0 and r[3] > 0
                    and not (r[0] == 0 and r[1] == 0)
                    and 0 <= r[0] < 6000 and 0 <= r[1] < 4000)

    def ui_tree(self, limit: int = 150):
        """Return visible, actionable UI elements from the guest's AT-SPI tree as
        [{"name","role","rect":[x,y,w,h] or None,"clickable":bool}]. `clickable`
        is False when the rect is bogus (GTK4 apps) — the caller should then act
        by AT-SPI action, vision, or shell instead of clicking the rect.

        Default limit is generous because file managers / icon grids put their
        cells deep in the tree (after the dock + window chrome); an 80-element cap
        truncated Nautilus folder/file cells, so the model never saw them and
        click_element could not resolve their rects."""
        rc, out, _ = self.run(
            self._session_env() + f"python3 {self._A11Y_REMOTE} {limit}", timeout=60)
        line = (out.strip().splitlines() or [""])[-1]
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict):
            return []
        for e in data:
            e["clickable"] = self._rect_clickable(e.get("rect"))
        return data

    def click_element(self, name=None, role=None, index=None, double=False):
        """Activate a UI element by name (preferred) or index, with a fallback
        chain. Returns (ok: bool, how: str) where how is:
          "rect"   — clicked its valid on-screen rect (a real click, so the widget
                     also gets keyboard focus — needed before keys like Enter/Delete)
          "action" — fired the element's AT-SPI action (coordinate-free fallback)
          "bogus"  — found, but no usable rect and the action failed (caller should
                     fall back to vision/screenshot or shell)
          "notfound" — no matching element in the tree

        Rect-first: now that bogus GTK4 rects are recovered (atspi_helper), a real
        click is preferable to the AT-SPI action — the action *selects* a grid cell
        in-model without giving the view keyboard focus, so a following Delete/Enter
        would miss. Fall back to the action only when the rect is bogus/unavailable.
        """
        import shlex
        els = self.ui_tree(limit=400)  # exhaustive: resolve the rect even for
        target = None                  # deep cells the model-facing tree may cap
        if index is not None and 0 <= index < len(els):
            target = els[index]
        elif name:
            target = next((e for e in els
                           if name.lower() in (e["name"] or "").lower()
                           and (role is None or role == e["role"])), None)
        if target is not None and target.get("clickable"):
            x, y, w, h = target["rect"]
            self.click(int(x + w / 2), int(y + h / 2), double=double)
            return True, "rect"
        # Rect missing or bogus: fall back to the coordinate-free AT-SPI action.
        if name:
            rc, out, _ = self.run(
                self._session_env()
                + f"python3 {self._A11Y_REMOTE} act {shlex.quote(name)}", timeout=60)
            try:
                res = json.loads((out.strip().splitlines() or [""])[-1])
                if isinstance(res, dict) and res.get("ok"):
                    return True, "action"
            except json.JSONDecodeError:
                pass
        return (False, "notfound") if target is None else (False, "bogus")


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
