"""
Registry extension for the full-ADB (text-only) agent.

Import this module before creating the agent runner so that
AGENT_GENERATOR_REGISTRY and AGENT_TRAJECTORY_REGISTRY contain the entries for
AndroidFullADBAgent.
"""

from skyrl_agent.agents.mapping import (
    AGENT_GENERATOR_REGISTRY,
    AGENT_TRAJECTORY_REGISTRY,
)

AGENT_GENERATOR_REGISTRY[
    "skyrl_agent.agents.android.AndroidFullADBAgent"
] = "skyrl_agent.agents.android.android_full_adb_runner.AndroidFullADBAgentRunner"

AGENT_TRAJECTORY_REGISTRY[
    "skyrl_agent.agents.android.AndroidFullADBAgent"
] = "skyrl_agent.agents.android.android_full_adb_trajectory.AndroidFullADBTrajectory"
