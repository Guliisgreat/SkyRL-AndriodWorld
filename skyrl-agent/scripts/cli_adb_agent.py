#!/usr/bin/env python3
"""
CLI runner for the ADB agent: load a task, connect to a container, run the
agent loop with an external LLM API (e.g. OpenAI), and report results.

Usage:
    cd skyrl-agent
    python scripts/cli_adb_agent.py \\
        --task-file data/uitars_easy_5tasks.jsonl \\
        --task-index 0 \\
        --model gpt-4o \\
        --api-url https://api.openai.com \\
        --max-steps 15 \\
        --skip-emulator
"""

import argparse
import asyncio
import base64
import io
import json
import os
import sys
import time

import numpy as np
import requests
from PIL import Image

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from skyrl_agent.agents.android.adb_agent import (
    build_initial_messages,
    append_assistant,
    append_adb_observation,
    apply_sliding_window,
    parse_adb_command,
    parse_task_control,
)


def _parse_args():
    p = argparse.ArgumentParser(description="Run ADB agent on a single AndroidWorld task.")
    p.add_argument("--task-file", required=True, help="JSONL file with task definitions")
    p.add_argument("--task-index", type=int, default=0, help="0-based index into the JSONL file")
    p.add_argument("--model", default="gpt-4o", help="LLM model name")
    p.add_argument("--api-url", default="https://api.openai.com", help="LLM API base URL")
    p.add_argument("--api-key", default=None, help="API key (default: $OPENAI_API_KEY)")
    p.add_argument("--max-steps", type=int, default=15, help="Max agent steps per task")
    p.add_argument("--max-history-steps", type=int, default=10, help="Sliding window size")
    p.add_argument("--server-port", type=int, default=5000, help="Container server port")
    p.add_argument("--skip-emulator", action="store_true",
                   help="Assume emulator/container is already running at --server-port")
    p.add_argument("--docker-image", default="androidworld-adb:v8",
                   help="Docker image when not using --skip-emulator")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    return p.parse_args()


def load_task(path: str, index: int) -> dict:
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]
    if index < 0 or index >= len(lines):
        raise IndexError(f"Task index {index} out of range (file has {len(lines)} tasks)")
    return json.loads(lines[index])


def _numpy_to_base64_data_uri(img: np.ndarray) -> str:
    pil = Image.fromarray(img)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _convert_messages_for_api(messages: list) -> list:
    """Convert internal message format to OpenAI Chat Completions API format."""
    api_msgs = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        if isinstance(content, str):
            api_msgs.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append({"type": "text", "text": block["text"]})
                    elif block.get("type") == "image":
                        data_uri = block.get("image", "")
                        if not data_uri.startswith("data:"):
                            data_uri = "data:image/png;base64," + data_uri
                        parts.append({
                            "type": "image_url",
                            "image_url": {"url": data_uri, "detail": "low"},
                        })
                else:
                    parts.append({"type": "text", "text": str(block)})
            api_msgs.append({"role": role, "content": parts})
            continue

        api_msgs.append({"role": role, "content": str(content)})
    return api_msgs


def call_llm(api_url: str, api_key: str, model: str, messages: list,
             max_tokens: int = 1024) -> str:
    """Call an OpenAI-compatible chat completions API."""
    url = f"{api_url.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": _convert_messages_for_api(messages),
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def get_observation(server_url: str) -> dict:
    """GET /health and return the current observation (screenshot)."""
    resp = requests.get(f"{server_url}/health", timeout=30)
    resp.raise_for_status()
    return resp.json()


def reset_env(server_url: str, task: dict) -> dict:
    """POST /reset to initialize the environment with a task."""
    payload = {"task": task.get("task", ""), "seed": task.get("seed", 0)}
    resp = requests.post(f"{server_url}/reset", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    obs = data.get("observation", {})
    if obs and "image" in obs:
        img_b64 = obs["image"]
        if isinstance(img_b64, str):
            raw = base64.b64decode(img_b64)
            obs["image"] = np.array(Image.open(io.BytesIO(raw)))
    return obs


def step_adb(server_url: str, command: str, thought: str) -> dict:
    """POST /step_adb to execute an ADB command."""
    payload = {"command": command, "thought": thought}
    resp = requests.post(f"{server_url}/step_adb", json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    obs = data.get("observation", {})
    if obs and "image" in obs:
        img_b64 = obs["image"]
        if isinstance(img_b64, str):
            raw = base64.b64decode(img_b64)
            obs["image"] = np.array(Image.open(io.BytesIO(raw)))
    return data


def step_task_control(server_url: str, action_dict: dict, thought: str) -> dict:
    """POST /step for FINISH/INFEASIBLE actions."""
    payload = {"action": action_dict, "thought": thought}
    resp = requests.post(f"{server_url}/step", json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    obs = data.get("observation", {})
    if obs and "image" in obs:
        img_b64 = obs["image"]
        if isinstance(img_b64, str):
            raw = base64.b64decode(img_b64)
            obs["image"] = np.array(Image.open(io.BytesIO(raw)))
    return data


def run_agent(args):
    task = load_task(args.task_file, args.task_index)
    task_text = task.get("task", "")
    print(f"Task {args.task_index}: {task_text}")

    server_url = f"http://localhost:{args.server_port}"
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")

    if not args.skip_emulator:
        print(f"Starting container with image {args.docker_image} ...")
        _start_container(args)

    print(f"Resetting environment at {server_url} ...")
    obs = reset_env(server_url, task)
    image = obs.get("image")
    if image is None:
        print("ERROR: No screenshot from /reset. Is the container running?")
        return False

    if not isinstance(image, np.ndarray):
        image = np.array(image)
    h, w = image.shape[0], image.shape[1]
    screen_resolution = (w, h)
    print(f"Screen: {w}x{h}")

    messages = build_initial_messages(
        task_text=task_text,
        screenshot=image,
        screen_resolution=screen_resolution,
    )

    for step_num in range(1, args.max_steps + 1):
        print(f"\n--- Step {step_num}/{args.max_steps} ---")

        selected = apply_sliding_window(messages, max_history_steps=args.max_history_steps)
        t0 = time.time()
        response_str = call_llm(args.api_url, api_key, args.model, selected)
        llm_time = time.time() - t0
        print(f"LLM response ({llm_time:.1f}s):")

        try:
            command, thought = parse_adb_command(response_str)
        except ValueError as e:
            print(f"  Parse error: {e}")
            print(f"  Raw: {response_str[:200]}")
            messages = append_assistant(messages, response_str)
            continue

        print(f"  Thought: {thought[:120]}")
        print(f"  Command: {command}")

        if command.startswith("FINISH") or command.startswith("INFEASIBLE"):
            action_dict = parse_task_control(command)
            data = step_task_control(server_url, action_dict, thought)
            reward = data.get("reward", 0.0)
            terminated = data.get("terminated", False)
            messages = append_assistant(messages, response_str)
            status = "FINISH" if command.startswith("FINISH") else "INFEASIBLE"
            print(f"\n=== {status} at step {step_num} | reward={reward} | terminated={terminated} ===")
            return reward > 0
        else:
            data = step_adb(server_url, command, thought)
            command_output = data.get("command_output", "")
            reward = data.get("reward", 0.0)
            terminated = data.get("terminated", False)
            truncated = data.get("truncated", False)

            if args.verbose and command_output:
                print(f"  Output: {command_output[:200]}")

            messages = append_assistant(messages, response_str)

            if terminated or truncated:
                status = "TERMINATED" if terminated else "TRUNCATED"
                print(f"\n=== {status} at step {step_num} | reward={reward} ===")
                return reward > 0

            obs = data.get("observation", {})
            image = obs.get("image") if obs else None
            if image is None:
                print("WARNING: No screenshot returned, ending episode.")
                return False

            if not isinstance(image, np.ndarray):
                image = np.array(image)
            h, w = image.shape[0], image.shape[1]
            screen_resolution = (w, h)

            messages = append_adb_observation(
                messages, image, command, command_output, "", 0, screen_resolution,
            )

    print(f"\n=== MAX STEPS REACHED ({args.max_steps}) ===")
    return False


def _start_container(args):
    """Start a container using ContainerManager (blocking)."""
    from skyrl_agent.runtime.android.container_manager import ContainerManager

    async def _create():
        manager = ContainerManager(docker_image=args.docker_image, temp_path="/tmp/cli_adb_agent")
        containers = await manager.create_pool_parallel(
            pool_size=1, buffer_size=0, base_env_id=0,
            max_concurrent=1, initial_wait=30.0, max_retries=1,
            sample_mode="sequential", snapshot="clean",
            train_task_family="android_world", val_task_family="android_world",
        )
        if not containers:
            raise RuntimeError("Failed to start container")
        args.server_port = containers[0].server_port
        print(f"Container running on port {args.server_port}")
        return manager

    asyncio.run(_create())


def main():
    args = _parse_args()
    success = run_agent(args)
    print(f"\nResult: {'SUCCESS' if success else 'FAILURE'}")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
