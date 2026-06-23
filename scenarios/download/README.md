# Scenario: cross-app (browser download → shell processing)

A multi-app agent flow that hands off between the **browser**, the **filesystem**,
and the **shell** — fully self-contained, nothing external.

`server.py` runs on the **host** (127.0.0.1:8001); the VM reaches it at
`http://10.0.2.2:8001`. The page has a **Download sales.csv** button (served with
`Content-Disposition: attachment`, so it lands in `~/Downloads`). The CSV has a
known total (**976.23**) so the agent's computed answer can be verified.

## Run it
```bash
# 1. Host: start the download server
python3 scenarios/download/server.py 8001

# 2. Spawn + boot Ubuntu, log in (QMP), open the page, then run the agent:
./spawn.sh ubuntu dl1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/dl1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Open http://10.0.2.2:8001, download sales.csv, then with the terminal sum the \
   'amount' column of ~/Downloads/sales.csv, write the total to ~/answer.txt, and \
   tell me the total."

# 3. Verify
#   ~/Downloads/sales.csv exists, ~/answer.txt == 976.23
```

## What it exercises
Browser (click a download) → filesystem (file appears in `~/Downloads`) → shell
(`run_bash` parses+sums the CSV) → persist (`~/answer.txt`) → report. Tests the
browser↔shell↔filesystem hand-offs in one task.

## Result (GPT-5, reasoning_effort=low)
Completed in **3 steps**: clicked Download, then one `run_bash` that parsed the
CSV with a robust Python reader (case-insensitive `amount` column, strips currency
chars), wrote `976.23` to `~/answer.txt`, and reported it. Verified against an
independent `awk` sum. (gpt-4o was not reliable enough for multi-step GUI; see
`scenarios/webmail/`.)
