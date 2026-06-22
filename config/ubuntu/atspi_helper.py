#!/usr/bin/env python3
"""AT-SPI2 helper — runs INSIDE the Ubuntu GNOME session.

Two modes:
  (default)  dump actionable on-screen elements as JSON [{name,role,rect}]
  act NAME   activate the element whose name matches NAME via the AT-SPI *action*
             interface (no coordinates) — robust to GTK4/libadwaita apps that
             report bogus (0,0) screen rects.

Needs DISPLAY / DBUS_SESSION_BUS_ADDRESS and `toolkit-accessibility true`.
"""
import json
import sys

import pyatspi

ACTIONABLE = {
    "push button", "toggle button", "check box", "radio button", "menu item",
    "check menu item", "radio menu item", "page tab", "link", "entry", "text",
    "list item", "tree item", "combo box", "slider", "spin button", "icon",
    "table cell",
}
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


def rect_of(acc):
    try:
        e = acc.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
        return [e.x, e.y, e.width, e.height]
    except Exception:
        return None


def dump(limit):
    out = []
    for app in apps():
        for acc in walk(app):
            if len(out) >= limit:
                break
            if not visible_actionable(acc):
                continue
            r = rect_of(acc)
            out.append({"name": (acc.name or "").strip(),
                        "role": acc.getRoleName(),
                        "rect": r if r and r[2] > 0 and r[3] > 0 else None})
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
