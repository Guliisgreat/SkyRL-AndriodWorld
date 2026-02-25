"""
Android Agent module for AndroidWorld GUI tasks.

This module provides:
- AndroidAgent: GUI agent following ReActAgent pattern
- AndroidTrajectory: Trajectory management following ReActTrajectory pattern
- AndroidAgentRunner: Runner using async_fix_pool dispatcher
- TrajectoryState: State container for trajectory data
- UITARS_USR_PROMPT_THOUGHT: Agent-specific prompt template
- Utilities: Pure functions for parsing, formatting, and selection

Note: Uses lazy imports to avoid requiring all dependencies at import time.
"""

__all__ = [
    # Classes
    "AndroidAgent",
    "AndroidAPIScreenAgent",
    "AndroidTrajectory",
    "AndroidAgentRunner",
    "AndroidAPIScreenADBAgent",
    "AndroidAPITreeADBAgent",
    "AndroidAPIComboAgent",
    "TrajectoryState",
    # Prompt template (agent-specific)
    "UITARS_USR_PROMPT_THOUGHT",
    # Utility functions
    "init_messages",
    "select_messages",
    "load_content",
    "numpy_to_base64",
    "parse_uitars_action",
    "add_box_token",
]


def __getattr__(name):
    """Lazy import for android agent classes to avoid dependency issues at import time."""
    # Agent classes and prompt (lazy loaded due to heavy dependencies)
    if name in ("AndroidAgent", "TrajectoryState", "UITARS_USR_PROMPT_THOUGHT"):
        from skyrl_agent.agents.android.android_agent import (
            AndroidAgent,
            TrajectoryState,
            UITARS_USR_PROMPT_THOUGHT,
        )
        return {
            "AndroidAgent": AndroidAgent,
            "TrajectoryState": TrajectoryState,
            "UITARS_USR_PROMPT_THOUGHT": UITARS_USR_PROMPT_THOUGHT,
        }[name]
    
    if name == "AndroidTrajectory":
        from skyrl_agent.agents.android.android_trajectory import AndroidTrajectory
        return AndroidTrajectory
    
    if name == "AndroidAgentRunner":
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        return AndroidAgentRunner
    
    if name == "AndroidAPIScreenADBAgent":
        from skyrl_agent.agents.android.android_api_screen_adb_agent import AndroidAPIScreenADBAgent
        return AndroidAPIScreenADBAgent
    
    if name == "AndroidAPITreeADBAgent":
        from skyrl_agent.agents.android.android_api_tree_adb_agent import AndroidAPITreeADBAgent
        return AndroidAPITreeADBAgent
    
    if name == "AndroidAPIScreenAgent":
        from skyrl_agent.agents.android.android_api_screen_agent import AndroidAPIScreenAgent
        return AndroidAPIScreenAgent
    
    if name == "AndroidAPIComboAgent":
        from skyrl_agent.agents.android.android_api_combo_agent import AndroidAPIComboAgent
        return AndroidAPIComboAgent
    
    if name in ("init_messages", "select_messages", "load_content", 
                "numpy_to_base64", "parse_uitars_action", "add_box_token"):
        from skyrl_agent.agents.android.android_utils import (
            init_messages,
            select_messages,
            load_content,
            numpy_to_base64,
            parse_uitars_action,
            add_box_token,
        )
        return {
            "init_messages": init_messages,
            "select_messages": select_messages,
            "load_content": load_content,
            "numpy_to_base64": numpy_to_base64,
            "parse_uitars_action": parse_uitars_action,
            "add_box_token": add_box_token,
        }[name]
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
