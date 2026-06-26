# Scenario: desktop app — Text Editor (create + Save As)

A pure **desktop-app grounding** flow, no host server. The agent opens the GNOME
**Text Editor** (super → "Text Editor"), types two exact lines, and uses **Save
As** to write the file to `~/Desktop/poem.txt`. The check reads that file back
over SSH and compares the content.

The hard part is grounding: typing into the editor and driving the GTK Save
dialog to an exact path. This is the difficult edge of computer-use — there is no
form to anchor on, just the app's own chrome.

## Run it
```bash
./spawn.sh ubuntu ed1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/ed1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Open the Text Editor and type exactly these two lines: 'Roses are red, violets \
   are blue,' then 'this VM is driven by an LLM for you.' Then Save As to \
   ~/Desktop/poem.txt."
# verify: ssh in and `cat ~/Desktop/poem.txt`
```

Scored suite:
```bash
control/.venv/bin/python control/evals.py --target ubuntu --scenario editor
```

## Note on shell shortcuts
The benchmark scores the **end state** (the saved file), so a capable agent could
also satisfy it with `run_bash` (`cat > ~/Desktop/poem.txt`). The eval report's
per-step trace shows which path the agent actually took — GUI editing vs. shell —
so this still measures desktop grounding when you read the trace (or run a
vision-only model). Tagged `hard`.
