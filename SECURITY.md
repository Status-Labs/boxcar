# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in Boxcar, please report it privately
rather than opening a public issue. Use GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
("Report a vulnerability" under the repository's **Security** tab), or email the
maintainer at ben.siewert86@gmail.com.

Please include steps to reproduce, the impact, and your environment. We aim to
acknowledge reports within a few days.

## Scope and threat model

Boxcar runs untrusted-ish workloads (an LLM driving a desktop) inside a QEMU/KVM
virtual machine. A few things to keep in mind:

- **The VM is the sandbox, not a security boundary you should fully trust.** Run
  Boxcar on a machine where a VM escape would not be catastrophic, and do not
  put production secrets inside guest VMs.
- **The agent can run arbitrary commands** (PowerShell over SSH on Windows, bash
  on Ubuntu) and control the GUI. Only give it tasks and credentials you are
  comfortable with it acting on.
- **Networking is QEMU user-mode NAT** — the guest has outbound internet. Treat
  anything the agent does online as untrusted automation.
- **Never commit API keys.** Keys live in `control/.env` (git-ignored). The
  committed `control/.env.example` must stay empty.

## Supported versions

This is an early-stage project; security fixes are applied to `main`.
