# Scenario: log in + draft an email reply

A **truly complex, multi-step** agent flow that's fully self-contained and safe —
no real email account, no credentials, nothing sent externally.

`server.py` is a tiny mock webmail (stdlib only) that runs **on the host**; the
VM's browser reaches it at `http://10.0.2.2:8000` (QEMU user-net gateway → host
loopback). It has a login page (`demo` / `demo`), an inbox with one seeded
message from "Dana", and an inline reply box. **Save draft** appends the reply to
`drafts.json` (git-ignored) so the flow can be verified.

## Run it
```bash
# 1. Host: start the mock webmail
python3 scenarios/webmail/server.py 8000

# 2. Spawn + boot an Ubuntu VM, log in (QMP), then point the agent at it:
./spawn.sh ubuntu mail1
VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/mail1-qmp.sock \
  control/.venv/bin/python control/agent_dspy.py --target ubuntu \
  "Open the browser to http://10.0.2.2:8000, sign in with demo/demo, open Dana's \
   email, write a reply agreeing to lunch Tuesday at noon, and click Save draft."

# 3. Verify
cat scenarios/webmail/drafts.json
```

## What it exercises
OS login (GDM) → launch browser → web login form → read a message → compose a
**contextual** reply → submit a form → persist. End state is a real saved draft.

## Findings

- **GPT-5 (`OPENAI_MODEL=gpt-5`, reasoning_effort=low): completes it.** Signed
  in, opened Dana's email, wrote a contextual reply, dismissed an unexpected
  "save password?" popup, and saved the draft — **12 steps**, end to end.
- **gpt-4o: fails.** Across 3 runs it did the sub-steps (login, open message) but
  was inconsistent on precise clicks (missed the Reply button, mis-hit form
  fields, typo-looped on the username) and never saved a draft in 40 steps.

So the harness/scenario were always sound; the bottleneck was the model. A
stronger driver (GPT-5 here) clears it. Note the accessibility tree (`--a11y`)
does NOT help this web flow — Linux/Firefox expose web-content a11y rects
unreliably — so GPT-5 succeeds purely on vision + the form recipe in the guide.
