AGENT_GENERATOR_REGISTRY = {
    "skyrl_agent.agents.oh_codeact.OHCodeActAgent": "skyrl_agent.agents.base.AgentRunner",
    "skyrl_agent.agents.react.ReActAgent": "skyrl_agent.agents.base.AgentRunner",
    "skyrl_agent.agents.android.AndroidAgent": "skyrl_agent.agents.android.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidADBAgent": "skyrl_agent.agents.android.android_adb_runner.AndroidADBAgentRunner",
    "skyrl_agent.agents.android.AndroidFullADBAgent": "skyrl_agent.agents.android.android_full_adb_runner.AndroidFullADBAgentRunner",
}

AGENT_TRAJECTORY_REGISTRY = {
    "skyrl_agent.agents.oh_codeact.OHCodeActAgent": "skyrl_agent.agents.oh_codeact.CodeActTrajectory",
    "skyrl_agent.agents.react.ReActAgent": "skyrl_agent.agents.react.ReActTrajectory",
    "skyrl_agent.agents.android.AndroidAgent": "skyrl_agent.agents.android.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidADBAgent": "skyrl_agent.agents.android.android_adb_trajectory.AndroidADBTrajectory",
    "skyrl_agent.agents.android.AndroidFullADBAgent": "skyrl_agent.agents.android.android_full_adb_trajectory.AndroidFullADBTrajectory",
}
