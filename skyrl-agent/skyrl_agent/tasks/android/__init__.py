"""
Android Task module for AndroidWorld tasks.

This module provides:
- AndroidTask: Task interface for Android/AndroidWorld tasks

Note: Agent-specific prompts are in skyrl_agent.agents.android.prompts
"""

from skyrl_agent.tasks.android.android_task import AndroidTask

__all__ = [
    "AndroidTask",
]
