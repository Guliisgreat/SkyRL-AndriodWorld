"""
Compatibility shim for ``skyrl_agent.runtime.android``.

Commit 237ab9e0 ("refactor: move runtime/brokers and utils to eval-runners/common/")
moved the entire contents of this package to ``eval-runners/common/runtime/``
but left numerous ``from skyrl_agent.runtime.android...`` imports scattered
across the agent and dispatcher code (e.g. ``tasks/android/android_task.py``,
``agents/android/runner.py``, ``agents/android/base.py``,
``dispatcher/dispatchers.py``). The eval-runners directory is not installed as
a Python package in the skyrl-agent venv, so those imports cannot resolve.

This shim redirects submodule lookup to the canonical eval-runners location by
setting ``__path__``, then execs the canonical ``__init__.py`` so the top-level
names (``ContainerManager``, ``RuntimeClient``, exception classes) are
available without an extra submodule import. Relative imports inside the
canonical files (``from .runtime_client import ...``) resolve against this
namespace via ``__path__``.
"""

import os as _os

_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))
# skyrl-agent/skyrl_agent/runtime/android -> ../../../.. = SkyRL-AndriodWorld
_REPO_ROOT = _os.path.abspath(_os.path.join(_THIS_DIR, "..", "..", "..", ".."))
_CANONICAL_DIR = _os.path.join(_REPO_ROOT, "eval-runners", "common", "runtime")

if not _os.path.isdir(_CANONICAL_DIR):
    raise ImportError(
        f"skyrl_agent.runtime.android shim expected canonical package at "
        f"{_CANONICAL_DIR} but the directory is missing. The eval-runners "
        "checkout may be incomplete."
    )

# Redirect submodule lookup. Order matters: keep this directory on the path too
# so existing subfolders like ``androidlab_docker/`` continue to resolve.
__path__ = [_CANONICAL_DIR, _THIS_DIR]

# Execute the canonical __init__.py in this namespace so its top-level
# exports (ContainerManager, RuntimeClient, ContainerError, ...) become
# attributes of ``skyrl_agent.runtime.android``.
_canonical_init = _os.path.join(_CANONICAL_DIR, "__init__.py")
with open(_canonical_init) as _f:
    exec(compile(_f.read(), _canonical_init, "exec"), globals())
