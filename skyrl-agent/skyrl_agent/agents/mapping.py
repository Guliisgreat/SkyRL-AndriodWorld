AGENT_GENERATOR_REGISTRY = {
    "skyrl_agent.agents.oh_codeact.OHCodeActAgent": "skyrl_agent.agents.base.AgentRunner",
    "skyrl_agent.agents.react.ReActAgent": "skyrl_agent.agents.base.AgentRunner",
    "skyrl_agent.agents.android.AndroidAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidAPIScreenADBAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidAPITreeADBAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidAPIScreenAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidAPIComboAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidM3AAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidT3AAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidT3AADBAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
    "skyrl_agent.agents.android.AndroidMobileUseAgent": "skyrl_agent.agents.android.android_runner.AndroidAgentRunner",
}

AGENT_TRAJECTORY_REGISTRY = {
    "skyrl_agent.agents.oh_codeact.OHCodeActAgent": "skyrl_agent.agents.oh_codeact.CodeActTrajectory",
    "skyrl_agent.agents.react.ReActAgent": "skyrl_agent.agents.react.ReActTrajectory",
    "skyrl_agent.agents.android.AndroidAgent": "skyrl_agent.agents.android.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidAPIScreenADBAgent": "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidAPITreeADBAgent": "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidAPIScreenAgent": "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidAPIComboAgent": "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidM3AAgent": "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidT3AAgent": "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidT3AADBAgent": "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory",
    "skyrl_agent.agents.android.AndroidMobileUseAgent": "skyrl_agent.agents.android.android_trajectory.AndroidTrajectory",
}
