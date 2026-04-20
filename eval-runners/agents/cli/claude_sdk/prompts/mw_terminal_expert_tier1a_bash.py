"""MobileWorld terminal expert — Tier 1a, Bash-only tools.

Identical prompt body to `mw_terminal_expert_tier1a`, but restricts the agent
to the Bash tool only — no native Read or Write. The agent must use
`mw_tools.py read-file` / `write-file` for file operations instead of Claude
Code's built-in Read/Write.

Tests whether the native Read/Write tools meaningfully help, or whether the
agent does fine with shell-based file access.

Body is loaded from mw_terminal_expert_tier1a.py via the same file-loader the
runner uses, to avoid duplicating ~150 lines.
"""

import importlib.util
import os

REQUIRED_TOOLS = "Bash(command:*)"
ENV_SCRIPT = "mw_tools"


def _load_tier1a_build():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "mw_terminal_expert_tier1a.py")
    spec = importlib.util.spec_from_file_location(
        "mw_terminal_expert_tier1a_inner", path,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_system_prompt


build_system_prompt = _load_tier1a_build()
