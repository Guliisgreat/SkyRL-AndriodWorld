#!/bin/bash
# Experiment: Opus 4.6, bash-only (optimized_terminal_v1 prompt)
cd "$(dirname "$0")"

# Override build_system_prompt to use v1 (bash-only)
export ANDROIDLAB_PROMPT_VERSION=v1

python run_claude_cli_androidlab.py \
  --data androidlab_tasks_evaluable.jsonl \
  --broker-url http://localhost:9200 \
  --pool-size 16 \
  --model claude-opus-4-6 \
  --max-turns 25 \
  "$@"
