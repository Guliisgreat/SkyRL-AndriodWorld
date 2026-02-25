#!/usr/bin/env python3
"""
Standalone AndroidWorld inference using any OpenAI-compatible API.

No vLLM, no Ray, no verl required — just an API key.

For OpenAI models (gpt-*, o1-*, o3-*), tiktoken is used automatically for
accurate token counting. For open-source models served via vLLM/SGLang,
pass --tokenizer to load the matching HuggingFace tokenizer.

Usage:
    # With OpenAI API (GPT-5-mini) — tiktoken used automatically:
    OPENAI_API_KEY=sk-... python run_openai_android_inference.py \
        --data ../../data/androidworld_generalization/unseen_task_instance/test_seed7.jsonl \
        --model gpt-5-mini

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


_OPENAI_MODEL_PREFIXES = ("gpt-", "o1-", "o3-", "o4-", "chatgpt-")


def _is_openai_model(model_name: str) -> bool:
    return any(model_name.startswith(p) for p in _OPENAI_MODEL_PREFIXES)


class TiktokenWrapper:
    """Wraps tiktoken to expose the subset of HuggingFace tokenizer API used by the agent."""

    def __init__(self, model_name: str):
        import tiktoken
        try:
            self._enc = tiktoken.encoding_for_model(model_name)
        except KeyError:
            self._enc = tiktoken.get_encoding("o200k_base")
        self._model = model_name
        print(f"Using tiktoken for {model_name} (encoding={self._enc.name}, vocab={self._enc.n_vocab})")

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        return self._enc.encode(text)

    def decode(self, token_ids: list[int], skip_special_tokens: bool = True) -> str:
        return self._enc.decode(token_ids)

    def apply_chat_template(
        self,
        messages,
        add_generation_prompt: bool = False,
        tokenize: bool = True,
        return_dict: bool = False,
        **kwargs,
    ):
        """Approximate token count by serializing messages to text and encoding.

        This is used only for context-length budgeting -- the actual API call
        sends the original messages, not these token IDs.
        """
        parts = []
        for msg in (messages if isinstance(messages, list) else [messages]):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = "\n".join(text_parts)
            parts.append(f"<|{role}|>\n{content}")
        if add_generation_prompt:
            parts.append("<|assistant|>\n")
        text = "\n".join(parts)

        if not tokenize:
            return text

        ids = self._enc.encode(text)
        if return_dict:
            return {"input_ids": ids}
        return ids


def _load_tokenizer(model_name: str, tokenizer_override: str = None):
    """Load the appropriate tokenizer: tiktoken for OpenAI models, HuggingFace otherwise."""
    if tokenizer_override:
        print(f"Loading HuggingFace tokenizer: {tokenizer_override}")
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(tokenizer_override, trust_remote_code=True)

    if _is_openai_model(model_name):
        return TiktokenWrapper(model_name)

    print(f"Loading HuggingFace tokenizer: {model_name}")
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)


def _setup_wandb(cfg, model_name: str):
    """Initialize wandb if configured in trainer.logger. Returns the wandb module or None."""
    loggers = cfg.get("trainer", {}).get("logger", ["console"])
    if isinstance(loggers, str):
        loggers = [loggers]
    if "wandb" not in loggers:
        return None

    try:
        import wandb

        project = cfg.get("trainer", {}).get("project_name", "skyrl-androidworld")
        experiment = cfg.get("trainer", {}).get("experiment_name", "")
        if not experiment:
            experiment = f"{model_name}_{time.strftime('%m%d_%H%M')}"

        entity = os.environ.get("WANDB_ENTITY", None)
        wandb.init(
            project=project,
            name=experiment,
            entity=entity,
            config={
                "model": model_name,
                "agent": cfg.get("agent_cls", ""),
                "max_iterations": cfg.get("generator", {}).get("max_iterations", 0),
                "max_prompt_length": cfg.get("generator", {}).get("max_prompt_length", 0),
                "pool_size": cfg.get("env", {}).get("pool_size", 0),
                "skip_screenshot": cfg.get("env", {}).get("skip_screenshot", False),
            },
        )
        print(f"WandB logging enabled: {wandb.run.url}")
        return wandb
    except ImportError:
        print("Warning: wandb not installed, skipping wandb logging")
        return None
    except Exception as e:
        print(f"Warning: Failed to setup wandb: {e}")
        return None


def _log_wandb(wb, metrics: dict, instance_rewards: list, output_dir: str):
    """Log metrics, results table, and artifacts to wandb."""
    if wb is None:
        return

    # Scalar metrics (filter out non-numeric for wandb.log)
    scalar_metrics = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
    wb.log(scalar_metrics, step=0)

    # Per-instance results table
    columns = ["instance_id", "task", "reward", "step_count", "input_tokens", "output_tokens"]
    table = wb.Table(columns=columns)
    for entry in instance_rewards:
        table.add_data(
            entry["instance_id"],
            entry["task"][:200],
            entry["reward"],
            entry["step_count"],
            entry["total_input_tokens"],
            entry["total_output_tokens"],
        )
    wb.log({"results": table}, step=0)

    # Save output files as artifact
    metrics_file = os.path.join(output_dir, "final_metrics.json")
    rewards_file = os.path.join(output_dir, "rewards.json")
    artifact = wb.Artifact(
        name=f"inference-{metrics.get('model', 'unknown')}-{time.strftime('%m%d_%H%M')}",
        type="results",
    )
    if os.path.exists(metrics_file):
        artifact.add_file(metrics_file)
    if os.path.exists(rewards_file):
        artifact.add_file(rewards_file)
    wb.log_artifact(artifact)

    wb.finish()
    print("WandB run finished.")


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
    model_name = args.model or cfg.generator.backend_config.model_name
    tokenizer = _load_tokenizer(model_name, args.tokenizer)

    # --- Setup wandb ---
    wb = _setup_wandb(cfg, model_name)

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

    # --- Log to wandb ---
    _log_wandb(wb, metrics, instance_rewards, args.output_dir)

    return 0 if mean_reward >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
