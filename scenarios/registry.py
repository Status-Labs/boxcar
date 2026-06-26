#!/usr/bin/env python3
"""Discover every scenario in this package.

Each scenario lives in its own subpackage (``scenarios/<name>/``) and exposes a
module-level ``SCENARIO`` (a `framework.Scenario`) in ``scenario.py``. This module
imports them all and offers a few selectors used by the eval runner and the
optimizer's rollout harness.

Importing this module requires the repo root on ``sys.path`` (so ``scenarios`` is
importable as a package); `evals.py` arranges that.
"""
from __future__ import annotations

import importlib
import os

from .framework import Scenario

_HERE = os.path.dirname(os.path.abspath(__file__))


def _discover() -> dict[str, Scenario]:
    found: dict[str, Scenario] = {}
    for name in sorted(os.listdir(_HERE)):
        d = os.path.join(_HERE, name)
        if name.startswith(("_", ".")) or not os.path.isdir(d):
            continue
        if not os.path.exists(os.path.join(d, "scenario.py")):
            continue
        mod = importlib.import_module(f"scenarios.{name}.scenario")
        sc = getattr(mod, "SCENARIO", None)
        if isinstance(sc, Scenario):
            found[sc.name] = sc
    return found


def all_scenarios() -> dict[str, Scenario]:
    """name -> Scenario for every discovered scenario."""
    return _discover()


def select(names=None, target=None, tags=None) -> list[Scenario]:
    """Filter scenarios by explicit names, OS target, and/or required tags.

    names : iterable of scenario names (default: all)
    target: keep only scenarios that run on this OS ("ubuntu"/"win11")
    tags  : keep only scenarios carrying ALL of these tags
    """
    out = list(all_scenarios().values())
    if names:
        want = set(names)
        out = [s for s in out if s.name in want]
    if target:
        out = [s for s in out if s.runs_on(target)]
    if tags:
        need = set(tags)
        out = [s for s in out if need.issubset(set(s.tags))]
    return sorted(out, key=lambda s: s.name)


def get(name: str) -> Scenario:
    sc = all_scenarios().get(name)
    if sc is None:
        raise KeyError(f"no scenario named {name!r} "
                       f"(have: {', '.join(sorted(all_scenarios()))})")
    return sc
