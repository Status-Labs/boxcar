#!/usr/bin/env python3
"""AT-SPI2 helper — runs INSIDE the Ubuntu GNOME session.

Two modes:
  (default)  dump actionable on-screen elements as JSON [{name,role,rect}]
  act NAME   activate the element whose name matches NAME via the AT-SPI *action*
             interface (no coordinates) — robust to GTK4/libadwaita apps that
             report bogus (0,0) screen rects.

Bogus-rect recovery (GTK4/libadwaita): many widgets report (0,0) for their screen
extents (ATSPI DESKTOP_COORDS), which is why coordinate clicks miss. But the
WINDOW-relative extents are correct — only the screen *anchor* is wrong. We
reconstruct the screen rect as:

    screen = X11_window_origin + _GTK_FRAME_EXTENTS(left,top) + WINDOW_COORDS

reading the window origin from the WM (xdotool) and GTK's published invisible
CSD-shadow margin (xprop _GTK_FRAME_EXTENTS). Requires xdotool + x11-utils in the
guest and an X11 session (this VM runs Xorg). Without those tools it degrades
gracefully to the old behavior (bogus rect -> caller falls back to action/vision).

Needs DISPLAY / DBUS_SESSION_BUS_ADDRESS and `toolkit-accessibility true`.
"""
import json
import re
import subprocess
import sys

import pyatspi

ACTIONABLE = {
    "push button", "toggle button", "check box", "radio button", "menu item",
    "check menu item", "radio menu item", "page tab", "link", "entry", "text",
    "list item", "tree item", "combo box", "slider", "spin button", "icon",
    "table cell",
}
FRAME_ROLES = {"frame", "window", "dialog", "file chooser", "alert"}
# Preferred action names, best first.
ACTION_PREF = ["click", "activate", "press", "open", "jump", "select"]


def apps():
    desktop = pyatspi.Registry.getDesktop(0)
    for i in range(desktop.childCount):
        try:
            a = desktop.getChildAtIndex(i)
        except Exception:
            continue
        if a is not None:
            yield a


def walk(root):
    stack = [root]
    while stack:
        acc = stack.pop()
        if acc is None:
            continue
        try:
            for i in range(acc.childCount):
                stack.append(acc.getChildAtIndex(i))
        except Exception:
            pass
        yield acc


def visible_actionable(acc):
    try:
        st = acc.getState()
        return (st.contains(pyatspi.STATE_SHOWING)
                and st.contains(pyatspi.STATE_VISIBLE)
                and acc.getRoleName() in ACTIONABLE)
    except Exception:
        return False


def _extents(acc, coord):
    try:
        e = acc.queryComponent().getExtents(coord)
        return [e.x, e.y, e.width, e.height]
    except Exception:
        return None


def _is_bogus(r):
    """A screen rect is unusable if it has no size or is piled at the origin."""
    return not (r and r[2] > 0 and r[3] > 0 and not (r[0] == 0 and r[1] == 0)
                and 0 <= r[0] < 6000 and 0 <= r[1] < 4000)


def _toplevel_frame(acc):
    cur, hops = acc, 0
    while cur is not None and hops < 50:
        try:
            if cur.getRoleName() in FRAME_ROLES:
                return cur
            cur = cur.parent
        except Exception:
            return None
        hops += 1
    return None


def _sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def window_anchors():
    """X11 window title -> visible-content origin (x, y), for bogus-rect recovery.
    Empty if xdotool/xprop are unavailable (then recovery is simply skipped)."""
    anchors = {}
    root = _sh("xprop", "-root", "_NET_CLIENT_LIST")
    for wid in re.findall(r"0x[0-9a-fA-F]+", root.split("#", 1)[-1] if "#" in root else ""):
        geo = _sh("xdotool", "getwindowgeometry", "--shell", wid)
        g = dict(ln.split("=", 1) for ln in geo.strip().splitlines() if "=" in ln)
        if "X" not in g or "Y" not in g:
            continue
        fe = _sh("xprop", "-id", wid, "_GTK_FRAME_EXTENTS")
        nums = [int(n) for n in fe.split("=")[-1].replace(",", " ").split()] \
            if "=" in fe else []
        nums = (nums + [0, 0, 0, 0])[:4]      # left, right, top, bottom
        name = _sh("xdotool", "getwindowname", wid).strip()
        if name:
            anchors[name] = (int(g["X"]) + nums[0], int(g["Y"]) + nums[2])
    return anchors


def _anchor_for(anchors, frame_name):
    if not frame_name:
        return None
    if frame_name in anchors:
        return anchors[frame_name]
    # loose match (AT-SPI frame name vs X11 _NET_WM_NAME can differ slightly)
    for title, origin in anchors.items():
        if frame_name in title or title in frame_name:
            return origin
    return None


def rect_for(acc, anchors):
    """Best screen rect for `acc`: the real DESKTOP rect if valid, else the
    GTK4-recovered rect (window origin + WINDOW_COORDS), else None."""
    screen = _extents(acc, pyatspi.DESKTOP_COORDS)
    if not _is_bogus(screen):
        return screen
    win = _extents(acc, pyatspi.WINDOW_COORDS)
    if win and win[2] > 0 and win[3] > 0:
        origin = _anchor_for(anchors, (_toplevel_frame(acc) or acc).name)
        if origin:
            return [origin[0] + win[0], origin[1] + win[1], win[2], win[3]]
    return None


def dump(limit):
    anchors = window_anchors()
    out = []
    for app in apps():
        for acc in walk(app):
            if len(out) >= limit:
                break
            if not visible_actionable(acc):
                continue
            out.append({"name": (acc.name or "").strip(),
                        "role": acc.getRoleName(),
                        "rect": rect_for(acc, anchors)})
        if len(out) >= limit:
            break
    print(json.dumps(out))


def act(name):
    needle = name.lower()
    for app in apps():
        for acc in walk(app):
            if not visible_actionable(acc):
                continue
            if needle not in (acc.name or "").lower():
                continue
            try:
                action = acc.queryAction()
            except Exception:
                continue
            names = [action.getName(i).lower() for i in range(action.nActions)]
            # Only succeed on a real *activating* action — never blindly fire
            # action[0] (it may be clipboard.copy etc., which "works" but is wrong).
            idx = next((names.index(p) for p in ACTION_PREF if p in names), None)
            if idx is None:
                continue
            action.doAction(idx)
            print(json.dumps({"ok": True, "did": names[idx], "name": acc.name}))
            return
    print(json.dumps({"ok": False, "reason": "no element with an activating action"}))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "act":
        act(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        dump(int(sys.argv[1]) if len(sys.argv) > 1 else 80)


if __name__ == "__main__":
    main()
