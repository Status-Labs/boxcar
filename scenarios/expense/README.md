# Scenario: read → compute → act (expense report)

Tests **arithmetic reasoning over a table**, not just transcription. The agent
must read a spend-vs-budget dashboard, work out which single category is over
budget and by how much (`spent − budget`), then file a report with that category
and overage amount.

`server.py` (host 127.0.0.1:8005; guest `http://10.0.2.2:8005`) shows four
categories; only **Travel** is over budget, by **312.50**. The submitted report is
appended to `report.json` (git-ignored) for scoring.

## Run it
```bash
python3 scenarios/expense/server.py 8005
./spawn.sh ubuntu ex1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/ex1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Open http://10.0.2.2:8005, find the one category over its monthly budget, then \
   in the report form enter that category and the overage amount (spent minus \
   budget) and click Submit report."
# verify: scenarios/expense/report.json == [{"category": "Travel", "amount": "312.50"}]
```

Scored suite:
```bash
control/.venv/bin/python control/evals.py --target ubuntu --scenario expense
```

## What it exercises
Reading tabular data, doing the subtraction to find the overage, and filling a
two-field form. Partial credit for getting the category right but the amount
wrong (or vice-versa) separates reasoning from arithmetic mistakes.
