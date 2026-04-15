#!/usr/bin/env python3
"""
Run original Android-Lab eval.py using our broker containers.

Monkey-patches Docker_Instance to use pre-existing broker containers
instead of creating new ones. The agent code, XML saving, and evaluation
are 100% original Android-Lab code — zero modifications.

Usage:
    python run_original_eval_with_broker.py \
        --broker-url http://localhost:9200 \
        --parallel 16 \
        --name gpt4o_broker_reproduce
"""

import argparse
import copy
import json
import os
import sys
import time
import urllib.request

# Must run from Android-Lab directory
ANDROID_LAB_DIR = "/shared/ligu/projects/SkyRL-AndriodWorld/Android-Lab"
os.chdir(ANDROID_LAB_DIR)
sys.path.insert(0, ANDROID_LAB_DIR)


def http_post(url, payload, timeout=300):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class BrokerDockerInstance:
    """Drop-in replacement for Docker_Instance that uses broker containers.

    Has the same interface as the original Docker_Instance:
    - initialize_single_task(config) → device name
    - stop_single_task()
    """

    def __init__(self, config, idx=0, broker_url="http://localhost:9200"):
        self.idx = idx
        self.config = config
        self.broker_url = broker_url
        self.container_id = None
        self.docker_port_local = None
        self.env_id = None

    def initialize_single_task(self, config):
        """Acquire container from broker, reset it, return device name."""
        self.config = config

        # Acquire from broker
        info = http_post(
            f"{self.broker_url}/acquire",
            {"pid": os.getpid(), "timeout": 300},
            timeout=300,
        )
        self.env_id = info["env_id"]
        self.docker_port_local = info["server_port"]
        self.container_id = info.get("container_id", f"env{self.env_id}")

        url = f"http://localhost:{self.docker_port_local}"

        # Reset container (snapshot restore)
        http_post(f"{url}/reset", {"seed": None, "options": {}}, timeout=300)

        # Wait for ready
        for _ in range(30):
            try:
                h = http_get(f"{url}/health", timeout=5)
                if h.get("ready"):
                    break
            except Exception:
                pass
            time.sleep(2)

        # Get device name from health
        try:
            h = http_get(f"{url}/health", timeout=5)
            device = h.get("device", f"emulator-{5554 + (self.env_id - 100) * 2}")
        except Exception:
            device = f"emulator-{5554}"

        # Create directories inside container (original eval expects these)
        from evaluation.docker_utils import execute_command_in_container
        try:
            execute_command_in_container(self.container_id, f"mkdir -p {config.task_dir}")
            execute_command_in_container(self.container_id, f"mkdir -p {config.trace_dir}")
            execute_command_in_container(self.container_id, f"mkdir -p {config.screenshot_dir}")
            execute_command_in_container(self.container_id, f"mkdir -p {config.xml_dir}")
        except Exception as e:
            print(f"  Warning: mkdir in container failed: {e}")

        time.sleep(5)
        return device

    def stop_single_task(self):
        """Return container to broker (don't destroy it)."""
        if self.env_id is not None:
            try:
                http_post(
                    f"{self.broker_url}/return",
                    {"env_id": self.env_id, "healthy": True},
                    timeout=60,
                )
            except Exception as e:
                print(f"  Warning: broker return failed: {e}")
            self.env_id = None

    def __del__(self):
        self.stop_single_task()


def main():
    parser = argparse.ArgumentParser(
        description="Run original eval.py with broker containers"
    )
    parser.add_argument("--broker-url", default="http://localhost:9200")
    parser.add_argument("--parallel", "-p", type=int, default=16)
    parser.add_argument("--name", "-n", default="gpt4o_broker_reproduce")
    parser.add_argument("--config", "-c", default=None)
    parser.add_argument("--task_id", nargs="+", default=None)
    parser.add_argument("--app", nargs="+", default=None)
    args = parser.parse_args()

    # Load config
    import yaml
    config_path = args.config or os.path.join(ANDROID_LAB_DIR, "configs/gpt-4o-reproduce.yaml")
    with open(config_path) as f:
        yaml_data = yaml.safe_load(f)

    agent_config = yaml_data["agent"]
    task_config = yaml_data["task"]
    eval_config = yaml_data["eval"]

    # Import original code
    from agent import get_agent
    from evaluation.auto_test import TextOnlyMobileTask_AutoTest
    from evaluation.configs import AppConfig, TaskConfig
    from generate_result import find_all_task_files
    from queue import Queue
    import concurrent.futures

    single_config = TaskConfig(**task_config["args"])
    single_config = single_config.add_config(eval_config)
    agent = get_agent(agent_config["name"], **agent_config["args"])

    task_yamls = [f"evaluation/config/{f}" for f in os.listdir("evaluation/config") if f.endswith(".yaml")]
    task_files = find_all_task_files(task_yamls)

    # Check already run
    save_dir = os.path.join(single_config.save_dir, args.name)
    if os.path.exists(save_dir):
        already_run = [
            i.split("_")[0] + "_" + i.split("_")[1]
            for i in os.listdir(save_dir)
        ]
    else:
        already_run = []

    # Build task list (same as original eval.py)
    all_tasks = []
    for app_task_config_path in task_files:
        app_config = AppConfig(app_task_config_path)
        task_ids = list(app_config.task_name.keys()) if args.task_id is None else args.task_id
        for task_id in task_ids:
            if task_id in already_run:
                print(f"Task {task_id} already run, skipping")
                continue
            if task_id not in app_config.task_name:
                continue
            task_instruction = app_config.task_name[task_id].strip()
            app = app_config.APP
            if args.app and app not in args.app:
                continue
            package = app_config.package
            command_per_step = app_config.command_per_step.get(task_id, None)
            task_instruction = f"You should use {app} to complete the following task: {task_instruction}"
            all_tasks.append({
                "agent": agent,
                "task_id": task_id,
                "task_instruction": task_instruction,
                "package": package,
                "command_per_step": command_per_step,
                "app": app,
            })

    print(f"Running {len(all_tasks)} tasks with {args.parallel} parallel workers")
    print(f"Using broker: {args.broker_url}")
    print(f"Save dir: {save_dir}")

    # Parallel execution using BrokerDockerInstance
    free_instances = Queue()
    for idx in range(args.parallel):
        inst = BrokerDockerInstance(
            single_config, idx=idx, broker_url=args.broker_url
        )
        free_instances.put(inst)

    def task_done_callback(future, inst, q):
        q.put(inst)

    config_sub = single_config.subdir_config(args.name)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
        task_list = list(all_tasks)
        while task_list:
            if free_instances.empty():
                time.sleep(0.5)
                continue

            instance = free_instances.get()
            task = task_list.pop(0)

            config_copy = copy.deepcopy(config_sub)
            auto_class = TextOnlyMobileTask_AutoTest(config_copy)

            future = executor.submit(auto_class.run_task, task, instance)
            future.add_done_callback(
                lambda fut, di=instance: task_done_callback(fut, di, free_instances)
            )

    print(f"\nAll tasks complete. Traces saved to: {save_dir}")
    print(f"Run generate_result.py to evaluate:")
    print(f"  cd {ANDROID_LAB_DIR}")
    print(f"  python generate_result.py --judge_model gpt-4o-2024-05-13")


if __name__ == "__main__":
    main()
