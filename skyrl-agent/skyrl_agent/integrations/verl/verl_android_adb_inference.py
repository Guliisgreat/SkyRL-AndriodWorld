# Copyright 2024 Bytedance Ltd. and/or its affiliates
"""
Inference entry point for AndroidWorld with ADB agent.

Registers the ADB agent (AndroidAPIScreenADBAgent -> AndroidADBAgentRunner) via mapping_adb
before running the same inference flow as verl_main_inference. Use with
+skyrl_agent.task_yaml=.../verl_android_adb_inference.yaml so agent_cls is AndroidAPIScreenADBAgent.
Containers must expose POST /step_adb (e.g. use the androidworld-adb image).
"""

# Register ADB agent and runner before any code that looks up AGENT_GENERATOR_REGISTRY
import skyrl_agent.agents.mapping_adb  # noqa: F401

from .verl_main_inference import main

if __name__ == "__main__":
    main()
