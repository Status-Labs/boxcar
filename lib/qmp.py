#!/usr/bin/env python3
"""Tiny QMP client for the VM control socket.

Usage:
  qmp.py <sock> autopress [key] [count]   # tap <key> once a second, <count> times
  qmp.py <sock> shot <out.png>            # save a PNG screenshot
"""
import json
import socket
import sys
import time


def connect(path, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(path)
            return s
        except OSError:
            time.sleep(0.5)
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    sock_path, cmd = sys.argv[1], sys.argv[2]
    s = connect(sock_path)
    if s is None:
        print(f"qmp: could not connect to {sock_path}", file=sys.stderr)
        return 0  # don't fail the VM launch
    f = s.makefile("rw")
    f.readline()  # greeting

    def call(obj):
        f.write(json.dumps(obj) + "\n")
        f.flush()
        return f.readline()
    call({"execute": "qmp_capabilities"})

    if cmd == "autopress":
        # Tap <key> every <interval>s, <count> times. Used to get past the
        # one-time "Press any key to boot from CD..." prompt. Keep the total
        # duration short (~12s) so presses don't bleed into the Setup GUI.
        key = sys.argv[3] if len(sys.argv) > 3 else "ret"
        count = int(sys.argv[4]) if len(sys.argv) > 4 else 24
        interval = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
        for _ in range(count):
            call({"execute": "send-key",
                  "arguments": {"keys": [{"type": "qcode", "data": key}]}})
            time.sleep(interval)
    elif cmd == "shot":
        out = sys.argv[3]
        print(call({"execute": "screendump",
                    "arguments": {"filename": out, "format": "png"}}).strip())
    elif cmd == "chord":
        # send one key combination, e.g.  chord ctrl shift ret
        keys = [{"type": "qcode", "data": k} for k in sys.argv[3:]]
        call({"execute": "send-key", "arguments": {"keys": keys}})
    elif cmd == "type":
        text = sys.argv[3]
        for ch in text:
            mods, base = char_to_qcode(ch)
            if base is None:
                continue
            keys = [{"type": "qcode", "data": m} for m in mods]
            keys.append({"type": "qcode", "data": base})
            call({"execute": "send-key", "arguments": {"keys": keys}})
            time.sleep(0.04)
    else:
        print(__doc__)
        return 1
    return 0


# --- character -> (modifiers, qcode) map for the `type` command --------------
_BASE = {
    ' ': 'spc', '-': 'minus', '=': 'equal', '[': 'bracket_left',
    ']': 'bracket_right', '\\': 'backslash', ';': 'semicolon',
    "'": 'apostrophe', '`': 'grave_accent', ',': 'comma', '.': 'dot',
    '/': 'slash',
}
_SHIFT = {
    '~': 'grave_accent', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0', '_': 'minus',
    '+': 'equal', '{': 'bracket_left', '}': 'bracket_right', '|': 'backslash',
    ':': 'semicolon', '"': 'apostrophe', '<': 'comma', '>': 'dot', '?': 'slash',
}


def char_to_qcode(ch):
    if ch.isalpha():
        return (['shift'] if ch.isupper() else []), ch.lower()
    if ch.isdigit():
        return [], ch
    if ch in _BASE:
        return [], _BASE[ch]
    if ch in _SHIFT:
        return ['shift'], _SHIFT[ch]
    if ch == '\n':
        return [], 'ret'
    if ch == '\t':
        return [], 'tab'
    return [], None


if __name__ == "__main__":
    sys.exit(main())
