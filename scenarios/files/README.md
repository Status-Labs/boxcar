# Scenario: desktop app — Files (click-navigate + act)

A pure **desktop-app grounding** flow, no host server. The agent opens GNOME
**Files** (super → "Files"), descends two folders by double-clicking
(`~/Workspace` → `inbox`), and moves a single file (`obsolete.txt`) to the Trash
by selecting it and pressing **Delete**. The check reads the guest filesystem
over SSH: `obsolete.txt` must leave `inbox` while `keep.txt` stays.

Where `editor` is keyboard-heavy (and so a noisy showcase for grounding), this
one is **click-bound**: the GUI path requires landing clicks on folder and file
**grid cells**, so it directly exercises the GTK4/libadwaita rect recovery in
`config/ubuntu/atspi_helper.py` — the fix that made those cells clickable by
name under `--a11y`. Two folder double-clicks to descend, one click to select the
file.

## Run it
```bash
./spawn.sh ubuntu fl1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/fl1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Open Files, double-click into Workspace then inbox, and move obsolete.txt to \
   the Trash (select it, press Delete). Leave keep.txt alone."
# verify: ssh in and `ls ~/Workspace/inbox`  (obsolete.txt gone, keep.txt present)
```

Scored suite:
```bash
control/.venv/bin/python control/evals.py --target ubuntu --scenario files
```

## Note on shell shortcuts
The benchmark scores the **end state** (the file removed from `inbox`), so a
capable agent could also satisfy it with `run_bash` (`rm`). The eval report's
per-step trace shows which path the agent actually took — clicking grid cells vs.
shell — so this still measures desktop grounding when you read the trace (or run
a vision-only model). Partial credit (0.6) if `obsolete.txt` is removed but
`keep.txt` is taken down with it. Tagged `hard`.
