#!/usr/bin/env python3
"""Demo of full Windows 11 VM control. Run after the VM is booted:

    cd control
    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python demo.py
"""
from config import load_env
from winvm import WinVM


def main():
    load_env()  # pull control/.env into the environment
    vm = WinVM()

    # --- OS-level control over SSH -----------------------------------------
    print("== whoami / versions (via SSH) ==")
    print(vm.powershell(
        "whoami; node --version; git --version; "
        "$env:COMPUTERNAME"))

    # --- visual control over QMP -------------------------------------------
    print("== screenshot -> desktop.png ==")
    vm.screenshot("desktop.png")

    print("== open Notepad and type into it ==")
    vm.run("start notepad")            # launch via SSH
    vm.sleep(2.5)
    vm.type("Hello from Python — driving Windows over QMP + SSH!\n")
    vm.sleep(0.5)
    vm.screenshot("notepad.png")
    print("saved desktop.png and notepad.png")

    vm.close()


if __name__ == "__main__":
    main()
