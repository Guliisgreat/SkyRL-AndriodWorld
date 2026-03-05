#!/usr/bin/env python3
"""
Standalone AndroidWorld evaluation using the Claude Agent SDK.

No vLLM, no Ray, no verl required — just an Anthropic API key.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python run_claude_sdk_android.py \
        --data ../../data/androidworld_generalization/unseen_task_instance/test.jsonl \
        --model claude-sonnet-4-20250514

    # Quick test (2 instances):
    python run_claude_sdk_android.py \
        --data ../../data/.../test.jsonl \
        --max-instances 2 --pool-size 2
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def load_jsonl(filepath: str) -> list:
    """Load AndroidWorld JSONL data."""
    items = []
    with open(filepath, "r") as f:
        for line_num, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            items.append({
                "instance_id": f"{entry.get('task_id', line_num)}_{entry.get('seed', 0)}",
                "instance": {
                    "task_id": entry.get("task_id", line_num),
                    "seed": entry.get("seed", 0),
                    "task": entry.get("task", ""),
                    "difficulty": entry.get("difficulty", ""),
                    "category": entry.get("category", ""),
                    "instance_id": f"{entry.get('task_id', line_num)}_{entry.get('seed', 0)}",
                },
                "data_source": "android_world",
                "raw_prompt": [{"role": "user", "content": entry.get("task", "")}],
            })
    return items


def main():
    parser = argparse.ArgumentParser(
        description="AndroidWorld evaluation via Claude Agent SDK"
    )
    parser.add_argument("--data", required=True, help="Path to test JSONL file")
    parser.add_argument(
        "--yaml",
        default=str(Path(__file__).parent / "claude_sdk_android.yaml"),
        help="Path to YAML config",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override Claude model (e.g. claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=None,
        help="Override env pool size",
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Limit number of instances (for debugging)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Override max turns per instance",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: ./results)",
    )
    args = parser.parse_args()

    # --- Validate API key ---
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    # --- Load data ---
    print(f"Loading data from {args.data}")
    data = load_jsonl(args.data)
    if args.max_instances:
        data = data[: args.max_instances]
    print(f"Loaded {len(data)} instances")

    # --- Load config ---
    from omegaconf import OmegaConf

    cfg = OmegaConf.load(args.yaml)
    OmegaConf.set_struct(cfg, False)

    # Apply CLI overrides
    if args.model:
        cfg.claude_sdk.model = args.model
    if args.max_turns:
        cfg.claude_sdk.max_turns = args.max_turns

    pool_size = args.pool_size
    if pool_size is None and os.environ.get("ENV_POOL_SIZE"):
        try:
            pool_size = int(os.environ["ENV_POOL_SIZE"])
        except ValueError:
            pass
    if pool_size is not None:
        cfg.env.pool_size = pool_size

    if args.output_dir:
        output_dir = args.output_dir
    else:
        model = cfg.claude_sdk.get("model", "claude-sonnet-4-20250514")
        model_short = model.rsplit("/", 1)[-1].replace("-", "").replace(".", "")
        exp_name = f"ClaudeAgentSDK_{model_short}_{time.strftime('%y%m%d_%H%M')}"
        output_dir = os.path.join("./results", exp_name)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    if "results" not in cfg:
        cfg.results = {}
    cfg.results.trajectory_save_dir = output_dir

    # --- Create runner ---
    # Load runner via direct file import to avoid skyrl_agent.agents.__init__
    # which pulls in verl/torch dependency chain.
    import importlib.util
    _runner_path = os.path.join(
        _PROJECT_ROOT, "skyrl_agent", "agents", "android", "claude_sdk", "runner.py"
    )
    _runner_spec = importlib.util.spec_from_file_location("claude_sdk_runner", _runner_path)
    _runner_mod = importlib.util.module_from_spec(_runner_spec)
    _runner_spec.loader.exec_module(_runner_mod)
    ClaudeSDKRunner = _runner_mod.ClaudeSDKRunner

    runner = ClaudeSDKRunner(cfg)

    # --- Print config ---
    model = cfg.claude_sdk.get("model", "claude-sonnet-4-20250514")
    max_turns = cfg.claude_sdk.get("max_turns", 30)
    env_pool_size = cfg.env.get("pool_size", 16)

    print(f"\n{'='*60}")
    print("AndroidWorld Claude Agent SDK Evaluation")
    print(f"{'='*60}")
    print(f"  Model:       {model}")
    print(f"  Max turns:   {max_turns}")
    print(f"  Instances:   {len(data)}")
    print(f"  Pool size:   {env_pool_size}")
    print(f"  Output:      {output_dir}")
    print(f"{'='*60}\n")

    # --- Run ---
    start = time.time()
    output = asyncio.run(runner.run(data, val_mode=True))
    elapsed = time.time() - start

    # --- Compute metrics ---
    rewards = output.get("rewards", [])
    step_counts = output.get("step_counts", [])
    mean_reward = sum(rewards) / max(len(rewards), 1)
    success_count = sum(1 for r in rewards if r > 0)

    metrics = {
        "model": model,
        "max_turns": max_turns,
        "num_instances": len(data),
        "mean_reward": mean_reward,
        "success_count": success_count,
        "success_rate": success_count / max(len(data), 1),
        "avg_steps": sum(step_counts) / max(len(step_counts), 1),
        "elapsed_seconds": elapsed,
    }
    if "rollout_metrics" in output:
        metrics.update(output["rollout_metrics"])

    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")
    print(f"{'='*60}")

    # --- Save ---
    metrics_file = os.path.join(output_dir, "final_metrics.json")
    with open(metrics_file, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nMetrics saved to: {metrics_file}")

    rewards_file = os.path.join(output_dir, "rewards.json")
    with open(rewards_file, "w") as f:
        instance_rewards = []
        for i, item in enumerate(data):
            entry = {
                "instance_id": item["instance_id"],
                "task": item["instance"].get("task", ""),
                "reward": rewards[i] if i < len(rewards) else 0.0,
                "step_count": step_counts[i] if i < len(step_counts) else 0,
            }
            instance_rewards.append(entry)
        json.dump(instance_rewards, f, indent=2)
    print(f"Per-instance rewards saved to: {rewards_file}")

    return 0 if mean_reward >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
