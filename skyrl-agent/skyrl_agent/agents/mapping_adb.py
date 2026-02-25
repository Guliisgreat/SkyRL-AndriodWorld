"""
Registry extension for ADB agent. Import this module before creating the agent runner
so that AGENT_GENERATOR_REGISTRY and AGENT_TRAJECTORY_REGISTRY contain the ADB entries.

All Android agents share AndroidAgentRunner; only the trajectory class differs.
"""

from skyrl_agent.agents.mapping import (
    AGENT_GENERATOR_REGISTRY,
    AGENT_TRAJECTORY_REGISTRY,
)

AGENT_GENERATOR_REGISTRY[
    "skyrl_agent.agents.android.AndroidAPIScreenADBAgent"
] = "skyrl_agent.agents.android.android_runner.AndroidAgentRunner"

AGENT_TRAJECTORY_REGISTRY[
    "skyrl_agent.agents.android.AndroidAPIScreenADBAgent"
] = "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory"
