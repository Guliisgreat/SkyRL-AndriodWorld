"""
Registry extension for ADB agent. Import this module before creating the agent runner
so that AGENT_GENERATOR_REGISTRY and AGENT_TRAJECTORY_REGISTRY contain the ADB entries.

Does not modify mapping.py; only adds new keys to the existing registries.
"""

from skyrl_agent.agents.mapping import (
    AGENT_GENERATOR_REGISTRY,
    AGENT_TRAJECTORY_REGISTRY,
)

AGENT_GENERATOR_REGISTRY[
    "skyrl_agent.agents.android.AndroidADBAgent"
] = "skyrl_agent.agents.android.android_adb_runner.AndroidADBAgentRunner"

AGENT_TRAJECTORY_REGISTRY[
    "skyrl_agent.agents.android.AndroidADBAgent"
] = "skyrl_agent.agents.android.android_adb_trajectory.AndroidADBTrajectory"
