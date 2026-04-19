"""System prompts for Claude Code CLI Android agent.

Each module exports a ``build_system_prompt(android_env_script: str) -> str``
function so callers can inject the path to the CLI wrapper at runtime.

Available prompts:
    adb_baseline    — one ADB command per step (default / baseline)
    codegen         — Python code generation for multi-step logic
"""
