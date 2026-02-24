# Copyright 2024 Bytedance Ltd. and/or its affiliates
"""
Inference entry point for AndroidWorld with text-only ADB agent (AndroidAPITreeADBAgent).

Registers the full-ADB agent via mapping_full_adb before running the same
inference flow as verl_main_inference. Use with
+skyrl_agent.task_yaml=.../verl_android_full_adb_inference.yaml so agent_cls
is AndroidAPITreeADBAgent.

This agent uses only the a11y tree (no screenshots) and outputs ADB commands.
"""

import skyrl_agent.agents.mapping_full_adb  # noqa: F401

from .verl_main_inference import main

if __name__ == "__main__":
    main()
