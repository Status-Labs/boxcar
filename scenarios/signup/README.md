# Scenario: multi-page sign-up wizard

A genuinely **multi-page web app** flow: the agent must navigate three pages in
order — **Account → Profile → Review → Create** — filling the right fields on
each, ticking a terms checkbox, and submitting. State is carried between pages in
hidden form fields, so nothing is recorded until the final submit appends the new
account to `accounts.json` (git-ignored), which is read back to verify.

`server.py` runs on the **host** (127.0.0.1:8003); the VM reaches it at
`http://10.0.2.2:8003`.

## Run it
```bash
# 1. Host: start the wizard
python3 scenarios/signup/server.py 8003

# 2. Spawn + boot Ubuntu, log in (QMP), then run the agent:
./spawn.sh ubuntu su1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/su1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Open http://10.0.2.2:8003 and complete the sign-up wizard. Step 1: username \
   'jdoe', email 'jdoe@acme.example', password 'Hunter2!'. Step 2: full name \
   'Jane Doe', company 'Acme', role 'Engineer'. Step 3: tick the terms box and \
   click Create account."

# 3. Verify
cat scenarios/signup/accounts.json     # or open http://10.0.2.2:8003/accounts
```

Or run it as part of the scored suite (see `docs/evals.md`):
```bash
control/.venv/bin/python control/evals.py --target ubuntu --scenario signup
```

## What it exercises
Multi-page navigation, per-page form filling, a checkbox, and a final submit. The
check awards partial credit per correct field (5 fields) and requires the terms
box to have been ticked, so a half-filled wizard scores below 1.0 instead of
passing.
