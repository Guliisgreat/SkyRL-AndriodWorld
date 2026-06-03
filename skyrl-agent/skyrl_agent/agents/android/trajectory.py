"""
Re-export shim for AndroidTrajectory.

Commit 237ab9e0 ("refactor: move runtime/brokers and utils to eval-runners/common/")
moved the canonical AndroidTrajectory implementation to
``eval-runners/common/utils/trajectory.py`` but did NOT update
``skyrl_agent/agents/android/__init__.py`` (which still does
``from skyrl_agent.agents.android.trajectory import AndroidTrajectory``).
This shim restores that import path by loading the canonical file directly
via importlib (eval-runners is not installed as a Python package in the
skyrl-agent venv, so a normal ``from ... import`` will not work).
"""

import importlib.util as _importlib_util
import os as _os

_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))
# skyrl-agent/skyrl_agent/agents/android -> ../../../../ = SkyRL-AndriodWorld
_REPO_ROOT = _os.path.abspath(_os.path.join(_THIS_DIR, "..", "..", "..", ".."))
_CANONICAL_PATH = _os.path.join(
    _REPO_ROOT, "eval-runners", "common", "utils", "trajectory.py"
)

if not _os.path.isfile(_CANONICAL_PATH):
    raise ImportError(
        f"AndroidTrajectory shim expected canonical file at {_CANONICAL_PATH} "
        "but it is missing. The eval-runners checkout may be incomplete."
    )

_spec = _importlib_util.spec_from_file_location(
    "_android_trajectory_canonical", _CANONICAL_PATH
)
_mod = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

AndroidTrajectory = _mod.AndroidTrajectory

__all__ = ["AndroidTrajectory"]
