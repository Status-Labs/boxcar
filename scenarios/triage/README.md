# Scenario: read → reason → act (issue triage)

Tests whether the agent can **reason over several items to pick the right one**
and then operate a **`<select>` dropdown** — not just transcribe a single value.

`server.py` (host 127.0.0.1:8004; guest `http://10.0.2.2:8004`) lists three
tickets. Exactly one is a critical **production outage** (#102); the others are a
typo and a nice-to-have. The agent must read them, choose the critical ticket in
the triage form, set **Priority = High** via the dropdown, and Submit. The
submission is appended to `triage.json` (git-ignored) for scoring.

## Run it
```bash
python3 scenarios/triage/server.py 8004
./spawn.sh ubuntu tr1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/tr1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Open http://10.0.2.2:8004, read the tickets, find the critical production \
   outage, select that ticket in the triage form, set its Priority to High, and \
   click Submit triage."
# verify: scenarios/triage/triage.json == [{"ticket": "102", "priority": "High"}]
```

Scored suite:
```bash
control/.venv/bin/python control/evals.py --target ubuntu --scenario triage
```

## What it exercises
Reasoning over multiple items (pick the outage, not the typo) plus driving a
`<select>` element. The check gives partial credit for the right ticket with the
wrong priority (or vice-versa), so reasoning and grounding failures are
distinguishable in the scorecard.
