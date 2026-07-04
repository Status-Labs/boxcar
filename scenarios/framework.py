#!/usr/bin/env python3
"""Scenario framework: turn a self-contained agent task into a scored benchmark.

A `Scenario` bundles four things:

  * task    — the natural-language goal handed to the agent (a string, or a
              function of the context so a web URL/port can be interpolated),
  * setup   — start any host-side mock server and reset state,
  * check   — read the *verifiable end state* and return pass/fail + a 0..1 score,
  * teardown— stop servers / clean up.

Web scenarios run a stdlib HTTP server on the HOST; the VM's browser reaches it at
``http://10.0.2.2:<port>`` (QEMU user-net gateway -> host loopback). Their state
lives in the server module (read directly by `check`, since the eval runner
serves the handler in-process). Desktop / shell scenarios have no server; their
`check` reads the guest filesystem over SSH via the `vm` handle.

`evals.py` enumerates scenarios from `registry.py`, runs each end to end, and
scores it with `check`.
"""
from __future__ import annotations

import http.server
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

# QEMU user-net gateway: from inside the guest, the host loopback is 10.0.2.2.
GUEST_GW = "10.0.2.2"


@dataclass
class CheckResult:
    """The verdict for one scenario run."""
    passed: bool
    score: float = 0.0          # 0..1 (partial credit allowed)
    detail: str = ""            # human-readable explanation (what was/ wasn't found)

    @classmethod
    def ok(cls, detail="", score=1.0):
        return cls(True, score, detail)

    @classmethod
    def fail(cls, detail="", score=0.0):
        return cls(False, score, detail)


@dataclass
class ScenarioContext:
    """Mutable per-run state handed to setup / check / teardown."""
    port: int = 0
    workdir: str = ""
    state: dict = field(default_factory=dict)
    _servers: list = field(default_factory=list)

    def guest_url(self, path: str = "/") -> str:
        return f"http://{GUEST_GW}:{self.port}{path}"

    def host_url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def serve(self, handler_cls) -> http.server.HTTPServer:
        """Start `handler_cls` on the host in a daemon thread. Binds the scenario's
        declared port (0 = any free port); updates ctx.port to the actual one."""
        srv = serve(handler_cls, port=self.port)
        self.port = srv.server_address[1]
        self._servers.append(srv)
        return srv

    def stop(self):
        for s in self._servers:
            try:
                s.shutdown()
                s.server_close()
            except Exception:  # noqa: BLE001
                pass
        self._servers.clear()


TaskSpec = Union[str, Callable[[ScenarioContext], str]]
CheckFn = Callable[[ScenarioContext, object], CheckResult]
# setup/teardown get (ctx, vm). Web scenarios ignore vm; desktop/shell scenarios
# use it to reset guest-side state over SSH before the run.
SetupFn = Callable[[ScenarioContext, object], None]


@dataclass
class Scenario:
    name: str                       # unique id, e.g. "signup"
    target: str                     # "ubuntu" | "win11" | "any"
    task: TaskSpec                  # the prompt (str or ctx -> str)
    check: CheckFn                  # (ctx, vm) -> CheckResult
    setup: SetupFn = lambda ctx, vm: None
    teardown: Optional[SetupFn] = None
    port: int = 0                   # default host port for web scenarios (0 = any)
    max_steps: int = 40
    tags: tuple = ()                # "web" | "desktop" | "shell" | "hard" ...
    summary: str = ""               # one line describing what it exercises

    def task_text(self, ctx: ScenarioContext) -> str:
        return self.task(ctx) if callable(self.task) else self.task

    def runs_on(self, target: str) -> bool:
        return self.target in ("any", target)


def serve(handler_cls, host: str = "127.0.0.1", port: int = 0) -> http.server.HTTPServer:
    """Start a threaded stdlib HTTP server in a daemon thread; return it.
    Caller stops it with .shutdown()/.server_close() (see ScenarioContext.stop)."""
    httpd = http.server.ThreadingHTTPServer((host, port), handler_cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# --------------------------------------------------------------------------- #
# Small helpers for desktop / shell scenario checks (guest-side, over SSH).
# --------------------------------------------------------------------------- #
def reset_browser(vm):
    """Close any browser left over from a prior run/sample (web-scenario setup).

    Each sample restarts the mock server, but the guest's browser is not
    stateless: a leftover window still shows the PREVIOUS sample's completed
    flow (e.g. a "Reminder sent!" confirmation page), so the agent — even when
    told to re-verify before finishing — sees a genuinely completed screen and
    reports done at step 2 without doing anything. Kill the browser so every
    sample starts from the desktop. (Same class of cross-sample contamination
    as the desktop apps' pkill in editor/settings setup.)

    NB: the [c] bracket keeps the -f pattern from matching this command's own
    `bash -c` wrapper over SSH (pkill only excludes its own pid, not its parent
    shell). TERM first so Chrome exits cleanly (no "restore pages?" crash
    bubble on relaunch); -9 catches any stragglers.
    """
    if vm is None:  # host-only tests drive scenarios without a VM
        return
    try:
        from winvm import WinVM
        if isinstance(vm, WinVM):
            vm.run("taskkill /im chrome.exe /f /t >nul 2>&1 & exit /b 0")
            return
        vm.run(f"pkill -u {vm.username} -f '[c]hrome' 2>/dev/null; true")
        vm.run("sleep 1")
        vm.run(f"pkill -9 -u {vm.username} -f '[c]hrome' 2>/dev/null; true")
    except Exception:  # noqa: BLE001 - best-effort cleanup must not fail setup
        pass


def read_guest_file(vm, path: str) -> Optional[str]:
    """Return the contents of a guest file, or None if it doesn't exist.
    Works on both targets (cat on Linux, type on Windows via the default shell)."""
    try:
        from winvm import WinVM
        if isinstance(vm, WinVM):
            rc, out, _ = vm.run(f'cmd /c if exist "{path}" type "{path}"')
            return out if rc == 0 and out.strip() else None
        rc, out, _ = vm.run(f'cat {shell_quote(path)} 2>/dev/null')
        return out if rc == 0 else None
    except Exception:  # noqa: BLE001
        return None


def guest_path_exists(vm, path: str) -> bool:
    try:
        from winvm import WinVM
        if isinstance(vm, WinVM):
            rc, out, _ = vm.run(f'cmd /c if exist "{path}" echo YES')
            return "YES" in out
        rc, _, _ = vm.run(f'test -e {shell_quote(path)}')
        return rc == 0
    except Exception:  # noqa: BLE001
        return False


def shell_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)
