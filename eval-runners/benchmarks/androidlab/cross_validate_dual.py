#!/usr/bin/env python3
"""
Cross-validate ADB verifiers against XML judges on same container state.

Monkey-patches Android-Lab's Docker_Instance.stop_single_task to run
ADB verification BEFORE the container is destroyed.

Usage:
    cd /shared/ligu/projects/SkyRL-AndriodWorld/Android-Lab
    source activate Android-Lab
    python ../skyrl-agent/examples/run_androidlab/cross_validate_dual.py
"""

import json
import os
import sys
import time

ANDROID_LAB_DIR = "/shared/ligu/projects/SkyRL-AndriodWorld/Android-Lab"
RUNNER_DIR = "/shared/ligu/projects/SkyRL-AndriodWorld/skyrl-agent/examples/run_androidlab"
sys.path.insert(0, RUNNER_DIR)
sys.path.insert(0, ANDROID_LAB_DIR)

os.chdir(ANDROID_LAB_DIR)

from verifiers.verifier_map import VERIFIER_MAP

# Collect ADB results
ADB_RESULTS = {}
CURRENT_TASK_ID = [None]

# Monkey-patch: inject ADB verification before container teardown
from evaluation import auto_test as _at

_original_stop = _at.Docker_Instance.stop_single_task

def _patched_stop(self):
    """Run ADB verifier before destroying the container."""
    tid = CURRENT_TASK_ID[0]
    if tid and tid in VERIFIER_MAP:
        try:
            url = f"http://localhost:{self.docker_port_local}"
            verifier = VERIFIER_MAP[tid](url)
            result = verifier.is_successful()
            ADB_RESULTS[tid] = result
            print(f"  [ADB verifier] {tid}: {result}")
        except Exception as e:
            ADB_RESULTS[tid] = {"error": str(e)}
            print(f"  [ADB verifier] {tid}: ERROR {e}")
    _original_stop(self)

_at.Docker_Instance.stop_single_task = _patched_stop

# Also patch run_task to track current task_id
_original_run_task = _at.AutoTest.run_task

def _patched_run_task(self, task_dict, instance):
    CURRENT_TASK_ID[0] = task_dict['task_id']
    _original_run_task(self, task_dict, instance)

_at.AutoTest.run_task = _patched_run_task

# Now run Android-Lab's eval.py normally
import yaml
from agent import get_agent
from evaluation.configs import AppConfig, TaskConfig
from generate_result import find_all_task_files

config_path = "configs/gpt-4o-reproduce.yaml"
with open(config_path) as f:
    yaml_data = yaml.safe_load(f)

agent_config = yaml_data["agent"]
task_config = yaml_data["task"]
eval_config = yaml_data["eval"]

single_config = TaskConfig(**task_config["args"])
single_config = single_config.add_config(eval_config)
agent = get_agent(agent_config["name"], **agent_config["args"])

task_yamls = [f"evaluation/config/{f}" for f in os.listdir("evaluation/config") if f.endswith(".yaml")]
task_files = find_all_task_files(task_yamls)

# Only operation tasks with ADB verifiers
all_tasks = []
for path in task_files:
    app_config = AppConfig(path)
    for tid in app_config.task_name:
        if tid not in VERIFIER_MAP:
            continue
        if app_config.metrics_type.get(tid) != "operation":
            continue
        task_text = app_config.task_name[tid].strip()
        all_tasks.append({
            "agent": agent,
            "task_id": tid,
            "task_instruction": f"You should use {app_config.APP} to complete the following task: {task_text}",
            "package": app_config.package,
            "command_per_step": app_config.command_per_step.get(tid),
            "app": app_config.APP,
        })

print(f"Dual evaluation: {len(all_tasks)} operation tasks")

# Run via Android-Lab's native eval
autotask_class = globals().get(task_config.get("class", "TextOnlyMobileTask_AutoTest"))
if autotask_class is None:
    from evaluation.auto_test import TextOnlyMobileTask_AutoTest
    autotask_class = TextOnlyMobileTask_AutoTest

auto_test = autotask_class(single_config.subdir_config("dual_eval"))
auto_test.run_serial(all_tasks)

# Save ADB results
output_path = "/tmp/dual_eval_adb_results.json"
with open(output_path, "w") as f:
    json.dump(ADB_RESULTS, f, indent=2)
print(f"\nADB results saved to {output_path}")
print(f"Tasks verified: {len(ADB_RESULTS)}")
adb_passed = sum(1 for r in ADB_RESULTS.values() if r.get("complete"))
print(f"ADB passed: {adb_passed}/{len(ADB_RESULTS)}")
