# Scenario: read → extract → act

Tests whether the agent can **reason over page content and act conditionally** —
not just follow rote steps.

`server.py` runs on the **host** (127.0.0.1:8002); the VM reaches it at
`http://10.0.2.2:8002`. It shows a read-only invoices table (one row is
**Overdue**: Globex Inc) plus a single "Send a reminder to [name]" form. The
agent must read the table, work out which customer is Overdue, type that name,
and Send. The typed name is recorded to `reminders.json` (git-ignored) for
verification.

## Run it
```bash
python3 scenarios/invoices/server.py 8002
./spawn.sh ubuntu inv1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/inv1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Read the invoices table, find the customer whose status is Overdue, type that \
   name into the 'Send a reminder to' box, and click Send reminder."
# verify: scenarios/invoices/reminders.json == [{"customer": "Globex Inc"}]
```

## Result (GPT-5) — and an important grounding finding

- **First design had a Remind button on every row.** GPT-5 **read and reasoned
  correctly** every time (its notes said "remind Globex Inc, the Overdue one")
  but its **click landed on the wrong row** — it anchored on the first row's
  button (Acme), repeatedly, even after the rows were spaced out. Vision LLMs are
  weak at absolute vertical position in a list; the cognition was right, the
  *grounding to a specific row* was not. It never recorded the correct customer.
- **Redesigned to a single form** (extract the name → type → Send): GPT-5
  completed it in **5 steps** and recorded exactly `Globex Inc`.

**Lesson:** the failure was grounding, not reasoning. For agent-friendly UIs,
prefer one unambiguous target over dense per-row controls — or use element
targeting (a11y / Set-of-Mark) for per-row actions. (Web-content a11y is
unreliable on Linux/Firefox, so per-row clicking there needs a stronger grounding
mechanism than pure vision.) Also keep the actionable element **above the fold** —
an over-tall table once pushed the form off-screen and the agent looped on
page-down.
