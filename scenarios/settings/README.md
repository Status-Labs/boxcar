# Scenario: desktop app — GNOME Settings (toggle Dark mode)

A **desktop-app navigation** flow, no host server. The agent opens the **Settings**
app (super → "Settings"), goes to **Appearance**, and switches the system style to
**Dark**. The end state is verifiable over SSH with no file to fake:
`org.gnome.desktop.interface color-scheme` must become `prefer-dark`.

`setup` forces the start state back to light (`default`) before each run, so
flipping to dark is always a real change.

## Run it
```bash
./spawn.sh ubuntu se1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/se1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Open the Settings app, go to Appearance, and switch the system style to Dark."
# verify (in the guest session):
#   gsettings get org.gnome.desktop.interface color-scheme   # -> 'prefer-dark'
```

Scored suite:
```bash
control/.venv/bin/python control/evals.py --target ubuntu --scenario settings
```

## What it exercises
Opening a real settings GUI, navigating to a section, and toggling a control —
verified through a side channel (`gsettings`) rather than a file the agent writes.
As with the editor scenario, a capable agent could flip this from the shell;
the step trace shows whether it navigated the GUI.
