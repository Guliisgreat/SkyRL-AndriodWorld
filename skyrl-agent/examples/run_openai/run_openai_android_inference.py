#!/usr/bin/env python3
"""
Standalone AndroidWorld inference using any OpenAI-compatible API.

No vLLM, no Ray, no verl required — just an API key.

A HuggingFace tokenizer is still loaded because the agent framework needs it
for context-length management, but the OpenAI chat backend sends the original
messages directly to the API — no tokenize/decode roundtrip.

Usage:
    # With OpenAI API (GPT-4o) — uses Qwen tokenizer for the agent internals:
    OPENAI_API_KEY=sk-... python run_openai_android_inference.py \
        --data ../../data/androidworld_generalization/unseen_task_instance/test.jsonl \
        --model gpt-4o --tokenizer Qwen/Qwen2-VL-7B-Instruct

    # With local vLLM server (completions mode, token IDs):
    OPENAI_API_KEY=dummy python run_openai_android_inference.py \
        --data test.jsonl --api-type completions \
        --model Qwen/Qwen2-VL-7B-Instruct --api-url http://localhost:8000
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from collections import defaultdict

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def load_jsonl(filepath: str) -> list:
    """Load AndroidWorld JSONL data into the format expected by AndroidAgentRunner."""
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
    parser = argparse.ArgumentParser(description="AndroidWorld inference via OpenAI API")
    parser.add_argument("--data", required=True, help="Path to test JSONL file")
    parser.add_argument(
        "--yaml",
        default=str(Path(__file__).parent / "openai_android_inference.yaml"),
        help="Path to agent YAML config",
    )
    parser.add_argument("--tokenizer", default=None, help="HuggingFace tokenizer name/path (default: from YAML model_name)")
    parser.add_argument("--model", default=None, help="Override API model name")
    parser.add_argument("--api-url", default=None, help="Override API URL")
    parser.add_argument("--api-type", default=None, choices=["chat", "completions"], help="Override API type")
    parser.add_argument("--output-dir", default="/tmp/openai_android_results", help="Output directory")
    parser.add_argument("--max-instances", type=int, default=None, help="Limit number of instances (for debugging)")
    args = parser.parse_args()

    # --- Load data ---
    print(f"Loading data from {args.data}")
    data = load_jsonl(args.data)
    if args.max_instances:
        data = data[:args.max_instances]
    print(f"Loaded {len(data)} instances")

    # --- Load config and apply overrides ---
    from omegaconf import OmegaConf

    cfg = OmegaConf.load(args.yaml)
    OmegaConf.set_struct(cfg, False)

    if args.model:
        cfg.generator.backend_config.model_name = args.model
    if args.api_url:
        cfg.generator.backend_config.api_url = args.api_url
    if args.api_type:
        cfg.generator.backend_config.api_type = args.api_type

    # --- Load tokenizer ---
    tokenizer_name = args.tokenizer or cfg.generator.backend_config.model_name
    print(f"Loading tokenizer: {tokenizer_name}")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name, trust_remote_code=True)

    # --- Register backend + build runner ---
    # Importing the module triggers register_backend("openai_server", ...)
    import skyrl_agent.integrations.openai  # noqa: F401

    from skyrl_agent.auto import AutoAgentRunner
    runner = AutoAgentRunner.from_task(args.yaml, infer_engine=None, tokenizer=tokenizer)

    # Apply CLI overrides to the already-loaded runner config
    if args.model:
        runner.cfg.generator.backend_config.model_name = args.model
    if args.api_url:
        runner.cfg.generator.backend_config.api_url = args.api_url
    if args.api_type:
        runner.cfg.generator.backend_config.api_type = args.api_type

    # Also update the already-constructed backend
    if args.model:
        runner.infer_engine.model_name = args.model
    if args.api_url:
        runner.infer_engine.api_url = args.api_url.rstrip("/")
    if args.api_type:
        runner.infer_engine.api_type = args.api_type

    # --- Run evaluation ---
    print(f"\n{'='*60}")
    print(f"Starting AndroidWorld OpenAI Inference")
    print(f"{'='*60}")
    print(f"  Model:       {runner.infer_engine.model_name}")
    print(f"  API URL:     {runner.infer_engine.api_url}")
    print(f"  API type:    {runner.infer_engine.api_type}")
    print(f"  Instances:   {len(data)}")
    print(f"  Output:      {args.output_dir}")
    print(f"{'='*60}\n")

    start = time.time()
    output = asyncio.run(runner.run(data, val_mode=True))
    elapsed = time.time() - start

    # --- Compute metrics ---
    rewards = output.get("rewards", [])
    mean_reward = sum(rewards) / max(len(rewards), 1)
    success_count = sum(1 for r in rewards if r > 0)

    metrics = {
        "model": runner.infer_engine.model_name,
        "num_instances": len(data),
        "mean_reward": mean_reward,
        "success_count": success_count,
        "success_rate": success_count / max(len(data), 1),
        "elapsed_seconds": elapsed,
    }

    # Add rollout metrics if available
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
    os.makedirs(args.output_dir, exist_ok=True)
    metrics_file = os.path.join(args.output_dir, "final_metrics.json")
    with open(metrics_file, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nMetrics saved to: {metrics_file}")

    # Save per-instance rewards (with step/token metrics when available)
    step_counts = output.get("step_counts", [])
    input_token_counts = output.get("input_token_counts", [])
    output_token_counts = output.get("output_token_counts", [])
    rewards_file = os.path.join(args.output_dir, "rewards.json")
    with open(rewards_file, "w") as f:
        instance_rewards = []
        for i, item in enumerate(data):
            entry = {
                "instance_id": item["instance_id"],
                "task": item["instance"].get("task", ""),
                "reward": rewards[i] if i < len(rewards) else 0.0,
                "step_count": step_counts[i] if i < len(step_counts) else 0,
                "total_input_tokens": input_token_counts[i] if i < len(input_token_counts) else 0,
                "total_output_tokens": output_token_counts[i] if i < len(output_token_counts) else 0,
            }
            instance_rewards.append(entry)
        json.dump(instance_rewards, f, indent=2)
    print(f"Per-instance rewards saved to: {rewards_file}")

    return 0 if mean_reward >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
