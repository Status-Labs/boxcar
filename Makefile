# Boxcar — convenience wrapper around the VM scripts, the agent, and the evals.
#
# The verbose bits (VM_SSH_PORT / VM_QMP_SOCK) are derived automatically from a
# clone's name: the QMP socket path is fixed, and the forwarded SSH port is read
# back from the running qemu process. So you just name the instance:
#
#   make up                      # spawn a fresh ubuntu clone "eval" (background)
#   make eval                    # run the whole scenario suite against it
#   make eval SCENARIO=webmail   # one scenario
#   make agent TASK="open a terminal and report the date"
#   make reset                   # delete the overlay -> clean on next spawn
#   make recreate                # reset + up (tear down and recreate)
#   make down                    # stop the VM
#
# Override any variable inline, e.g.  make eval TARGET=ubuntu NAME=ci PROVIDER=openai
.DEFAULT_GOAL := help
SHELL := /bin/bash

# ---- knobs -----------------------------------------------------------------
# Keep NO inline comments on these lines: trailing text before a '#' becomes part
# of the value in Make. Override inline, e.g. `make eval NAME=ci PROVIDER=openai`.
# TARGET: ubuntu|win11   NAME: clone instance name
TARGET   ?= ubuntu
NAME     ?= eval
# PROVIDER: anthropic|openai (blank = .env default).  SCENARIO: comma list (blank = all).
PROVIDER ?=
SCENARIO ?=
# SAMPLES: run each scenario N times for a pass-RATE (blank/1 = single run).
SAMPLES  ?=
# NAMES: comma list of clone names for `eval-parallel` (blank = all running clones).
NAMES    ?=
# TASK: one-off task for `make agent`.  EVAL_ARGS/OPT_ARGS: extra flag passthrough.
TASK     ?=
PY       ?= control/.venv/bin/python
EVAL_ARGS ?=
OPT_ARGS ?=

# ---- derived (strip guards against accidental trailing spaces) -------------
T        := $(strip $(TARGET))
N        := $(strip $(NAME))
FULLNAME := $(T)-$(N)
CLONES   := vms/$(T)/clones
SOCK     := $(CLONES)/$(N)-qmp.sock
PROVIDER_ARG := $(if $(strip $(PROVIDER)),--provider $(strip $(PROVIDER)),)
SCEN_ARG     := $(if $(strip $(SCENARIO)),--scenario $(strip $(SCENARIO)),)
SAMPLES_ARG  := $(if $(strip $(SAMPLES)),--samples $(strip $(SAMPLES)),)
NAMES_ARG    := $(if $(strip $(NAMES)),--names $(strip $(NAMES)),)
# Read the forwarded SSH port back out of the running qemu cmdline for this clone.
PORT_CMD = ps -ww -o args= -C qemu-system-x86_64 2>/dev/null \
  | grep -F -- "-name $(FULLNAME)" \
  | grep -oE 'hostfwd=tcp:127.0.0.1:[0-9]+' | grep -oE '[0-9]+$$' | head -1

.PHONY: help venv lint test spawn up down reset recreate ps eval eval-parallel \
        agent bootstrap optimize clean install bake

help: ## Show this help
	@echo "Boxcar make targets (vars: TARGET=$(T) NAME=$(N)):"
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ============================================================================ #
# Dev (no VM needed)
# ============================================================================ #
venv: ## Create control/.venv and install requirements
	python3 -m venv control/.venv
	control/.venv/bin/pip install -q -r control/requirements.txt
	@echo "venv ready: $(PY)"

lint: ## flake8 + compileall (mirrors CI)
	$(PY) -m flake8 --show-source --statistics
	$(PY) -m compileall -q control scenarios lib config/ubuntu
	@echo "lint OK"

test: ## Host-only scenario tests (servers + scoring, no VM)
	$(PY) -m scenarios.test_scenarios

optimize: ## Compile the per-OS policy (optimize.py; no VM)
	$(PY) control/optimize.py --target $(T) $(PROVIDER_ARG) $(OPT_ARGS)

clean: ## Remove generated reports, rollouts, compiled policy, scenario state
	rm -rf control/optim/reports control/optim/rollouts
	rm -f control/optimized_*.json
	rm -f scenarios/webmail/drafts.json scenarios/invoices/reminders.json \
	      scenarios/signup/accounts.json scenarios/triage/triage.json \
	      scenarios/expense/report.json
	@echo "cleaned generated artifacts"

# ============================================================================ #
# VM lifecycle (golden image + disposable clones)
# ============================================================================ #
install: ## Unattended install + provision the base VM (./<target>.sh install)
	./$(T).sh install

bake: ## Bake the provisioned disk into a golden base image
	./$(T).sh bake

spawn: ## Spawn the clone in the FOREGROUND (blocks this terminal)
	./spawn.sh $(T) $(N)

up: ## Spawn the clone in the BACKGROUND and wait until it's running
	@mkdir -p $(CLONES)
	@if [ -n "$$($(PORT_CMD))" ]; then echo "$(FULLNAME) already running (ssh:$$($(PORT_CMD)))"; exit 0; fi
	@nohup ./spawn.sh $(T) $(N) > $(CLONES)/$(N).log 2>&1 & \
	  echo "spawning $(FULLNAME) (log: $(CLONES)/$(N).log)..."
	@for i in $$(seq 1 30); do sleep 1; \
	  port=$$($(PORT_CMD)); \
	  if [ -n "$$port" ]; then echo "✓ up — ssh:$$port  qmp:$(SOCK)"; \
	    echo "  next: log it into the desktop, then 'make eval NAME=$(N)'"; exit 0; fi; \
	  done; \
	  echo "✗ $(FULLNAME) did not start in 30s — see $(CLONES)/$(N).log"; exit 1

down: ## Stop the running clone (leaves the overlay on disk)
	@if [ -n "$$($(PORT_CMD))" ]; then pkill -f -- "-name $(FULLNAME)" && echo "stopped $(FULLNAME)"; \
	  else echo "no running $(FULLNAME)"; fi
	@rm -f $(SOCK)

reset: ## Stop + delete the overlay (clean state from base on next spawn)
	@$(MAKE) --no-print-directory down TARGET=$(T) NAME=$(N)
	@rm -rf $(CLONES)/$(N).qcow2 $(CLONES)/$(N)-vars.fd \
	        $(CLONES)/$(N)-tpm $(CLONES)/$(N).log
	@echo "reset $(FULLNAME) — overlay deleted (recreated from base on next spawn)"

recreate: ## reset + up (tear down and bring back a clean clone)
	@$(MAKE) --no-print-directory reset TARGET=$(T) NAME=$(N)
	@$(MAKE) --no-print-directory up    TARGET=$(T) NAME=$(N)

ps: ## List running clones for this target
	@pgrep -af "qemu-system.*-name $(T)-" || echo "no $(T) clones running"

# ============================================================================ #
# Run against a clone (port/sock derived automatically)
# ============================================================================ #
eval: ## Run the scenario suite (SCENARIO=subset; SAMPLES=5 for pass-rate; EVAL_ARGS=--trace)
	@port=$$($(PORT_CMD)); \
	  [ -n "$$port" ] || { echo "✗ no running $(FULLNAME) — 'make up NAME=$(N)'"; exit 1; }; \
	  echo ">> $(FULLNAME)  ssh:$$port  qmp:$(SOCK)"; \
	  VM_SSH_PORT=$$port VM_QMP_SOCK=$(SOCK) \
	    $(PY) control/evals.py --target $(T) $(PROVIDER_ARG) $(SCEN_ARG) $(SAMPLES_ARG) $(EVAL_ARGS)

eval-parallel: ## Shard the suite across running clones (NAMES=a,b,c or all; SAMPLES=K)
		@$(PY) control/eval_parallel.py --target $(T) $(NAMES_ARG) $(PROVIDER_ARG) \
		  $(SCEN_ARG) $(SAMPLES_ARG) $(EVAL_ARGS)

agent: ## Drive a one-off task (TASK="...") against the clone
	@port=$$($(PORT_CMD)); \
	  [ -n "$$port" ] || { echo "✗ no running $(FULLNAME) — 'make up NAME=$(N)'"; exit 1; }; \
	  echo ">> $(FULLNAME)  ssh:$$port  qmp:$(SOCK)"; \
	  VM_SSH_PORT=$$port VM_QMP_SOCK=$(SOCK) \
	    $(PY) control/agent_dspy.py --target $(T) $(PROVIDER_ARG) "$(TASK)"

bootstrap: ## Harvest demos from passing runs (SCENARIO=... optional)
	@port=$$($(PORT_CMD)); \
	  [ -n "$$port" ] || { echo "✗ no running $(FULLNAME) — 'make up NAME=$(N)'"; exit 1; }; \
	  VM_SSH_PORT=$$port VM_QMP_SOCK=$(SOCK) \
	    $(PY) control/bootstrap_rollouts.py --target $(T) $(PROVIDER_ARG) $(SCEN_ARG)
