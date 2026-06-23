# Contributing to Boxcar

Thanks for your interest in improving Boxcar! This project lets LLM agents
safely drive a real Windows 11 / Ubuntu desktop inside a disposable QEMU/KVM
VM. Contributions of all kinds are welcome — bug reports, docs, new scenarios,
provider backends, OS guides, and code.

## Ways to contribute

- **Report a bug** — open an issue with the bug template. Include your host OS,
  QEMU version (`qemu-system-x86_64 --version`), the command you ran, and logs.
- **Suggest a feature** — open an issue with the feature template.
- **Add a scenario** — a self-contained demo task lives in `scenarios/<name>/`
  (see `scenarios/webmail/` for the pattern). Great first contribution.
- **Improve an OS guide** — `control/guides/{ubuntu,windows}.md` are the agent's
  domain knowledge and the highest-leverage place to fix grounding misses.
- **Add a provider backend** — implement a small class with a `step()` method in
  `control/backends.py` and register it in `make_backend()`.

## Development setup

You need a Linux host with KVM (`/dev/kvm`), `qemu-system-x86_64`, `qemu-img`,
`swtpm`, and OVMF firmware. See the [README](README.md#requirements) for the
full list and the installer ISOs.

```bash
git clone https://github.com/<your-username>/boxcar.git
cd boxcar/control
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

You can develop and test most of the Python control layer (`backends.py`,
`os_context.py`, the scenario servers) without a running VM. End-to-end agent
runs require a baked VM — see the [golden images guide](docs/golden-images.md).

## Before you open a pull request

1. **Branch** off `main` and keep PRs focused on one change.
2. **Lint** the Python: `flake8` (config in `setup.cfg`, max line length 100).
3. **Compile-check**: `python -m compileall control scenarios lib`.
4. **Update docs** — if you change behavior, update the `README.md` and any
   relevant guide. Keep the README's file table in sync if you add files.
5. **Add a changelog entry** under `## [Unreleased]` in `CHANGELOG.md`.
6. **Describe** what changed and how you tested it in the PR description.

## Commit & PR conventions

- Write clear, imperative commit messages ("Add invoices scenario", not
  "added stuff").
- Reference any related issue (`Fixes #123`).
- Be kind in review. See our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE) that covers this project.
