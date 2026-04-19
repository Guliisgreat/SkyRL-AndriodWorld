#!/usr/bin/env python3
"""
Generate ground truth trajectories in ATIF (Harbor) format for MobileWorld GUI-only tasks.

Reads from ground_truth_cli_finder.py's @gt() functions and converts each task's
CLI commands into an ATIF-v1.4 trajectory with proper step structure.

Usage:
    # Generate from a completed ground truth run
    python generate_gt_atif.py --results /tmp/gt_full_run.jsonl --output gt_trajectories.jsonl

    # Generate from live container (runs each task and records trajectory)
    python generate_gt_atif.py --live \
        --container-url http://localhost:6809 \
        --adb-serial "docker:mobile_world_env_5:emulator-5554" \
        --output gt_trajectories.jsonl
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone


def make_atif_trajectory(task_name, task_goal, steps_data, reward,
                          model_name="ground_truth_cli", agent_name="gt_cli_finder"):
    """Convert a task's ground truth execution into ATIF-v1.4 format."""
    now = datetime.now(timezone.utc).isoformat()

    # Build steps
    steps = []

    # Step 1: System message with task goal
    steps.append({
        "step_id": 1,
        "timestamp": now,
        "source": "user",
        "message": task_goal,
    })

    # Steps 2+: Agent actions (each CLI command = one step with tool_call + observation)
    step_id = 2
    for cmd_record in steps_data:
        action_type = cmd_record.get("action_type", "adb")
        params = cmd_record.get("action_params", {})
        output = cmd_record.get("command_output", "")

        # Build tool call
        if action_type == "adb":
            function_name = "adb_shell"
            arguments = {"command": params.get("command", "")}
        elif action_type == "sql":
            function_name = "sql_query"
            arguments = {"db_path": params.get("db_path", ""), "sql": params.get("sql", "")}
        elif action_type == "write-file":
            function_name = "write_file"
            arguments = {"path": params.get("device_path", ""),
                         "content_length": params.get("content_length", 0)}
        elif action_type == "read-file":
            function_name = "read_file"
            arguments = {"path": params.get("device_path", "")}
        elif action_type == "http":
            function_name = "http_request"
            arguments = {"method": params.get("method", "GET"), "url": params.get("url", "")}
        elif action_type == "finish":
            function_name = "finish"
            arguments = {"status": params.get("status", "complete"),
                         "description": params.get("description", "")}
        else:
            function_name = action_type
            arguments = params

        tool_call_id = f"tc_{step_id}"

        step = {
            "step_id": step_id,
            "timestamp": now,
            "source": "agent",
            "message": cmd_record.get("thought", ""),
            "model_name": model_name,
            "tool_calls": [{
                "tool_call_id": tool_call_id,
                "function_name": function_name,
                "arguments": arguments,
            }],
            "observation": {
                "results": [{
                    "source_call_id": tool_call_id,
                    "content": output[:2000] if output else "",
                }],
            },
        }
        steps.append(step)
        step_id += 1

    # Final step: finish
    steps.append({
        "step_id": step_id,
        "timestamp": now,
        "source": "agent",
        "message": "Task completed.",
        "tool_calls": [{
            "tool_call_id": f"tc_{step_id}",
            "function_name": "finish",
            "arguments": {"status": "complete", "description": "Ground truth CLI solution executed."},
        }],
    })

    trajectory = {
        "schema_version": "ATIF-v1.4",
        "session_id": f"gt_mobileworld_{task_name}",
        "agent": {
            "name": agent_name,
            "version": "1.0.0",
            "model_name": model_name,
            "extra": {
                "benchmark": "MobileWorld",
                "task_name": task_name,
                "task_type": "gui_only",
                "ground_truth": True,
            },
        },
        "steps": steps,
        "final_metrics": {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cached_tokens": 0,
            "total_cost_usd": 0.0,
            "total_steps": len(steps),
            "reward": reward,
        },
    }

    return trajectory


def generate_from_results(results_path, output_path):
    """Generate ATIF trajectories from a ground truth results JSONL file."""
    trajectories = []

    with open(results_path) as f:
        for line in f:
            result = json.loads(line)
            task_name = result.get("task_name", "")
            status = result.get("status", "")
            reward = result.get("score", 0.0)
            task_goal = result.get("task", task_name)

            if status in ("gui_required", "no_solution"):
                continue

            # Extract step records if available
            steps_data = result.get("commands", [])

            trajectory = make_atif_trajectory(
                task_name=task_name,
                task_goal=task_goal,
                steps_data=steps_data,
                reward=reward,
            )
            trajectories.append(trajectory)

    with open(output_path, "w") as f:
        for traj in trajectories:
            f.write(json.dumps(traj, ensure_ascii=False) + "\n")

    print(f"Generated {len(trajectories)} ATIF trajectories → {output_path}")
    passed = sum(1 for t in trajectories if t["final_metrics"]["reward"] > 0)
    print(f"  Passed: {passed}/{len(trajectories)}")
    return trajectories


def generate_from_live(container_url, adb_serial, device_id, output_path, container_name=""):
    """Run ground truth on live container and generate ATIF trajectories."""
    # Import the ground truth functions
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ground_truth_cli_finder import (
        GROUND_TRUTH, GUI_REQUIRED, init_task, eval_task, teardown_task,
        send_answer, wait_adb, check_health, http_get, write_file,
        NEEDS_SERVER_RESTART, restart_mw_server,
    )

    if container_name:
        os.environ["MW_DOCKER_CONTAINER"] = container_name

    if not check_health(container_url):
        print(f"ERROR: Container at {container_url} not healthy")
        return []

    # Get task list from server
    try:
        all_tasks = http_get(f"{container_url}/task/list")
        exclude_tags = {"agent-mcp", "agent-user-interaction"}
        task_names = [
            t["name"] for t in all_tasks
            if not (set(t.get("tags", [])) & exclude_tags)
        ]
    except Exception:
        task_names = sorted(GROUND_TRUTH.keys())

    trajectories = []
    out = open(output_path, "w")

    for i, task_name in enumerate(task_names):
        if task_name not in GROUND_TRUTH:
            continue

        print(f"\n[{i+1}/{len(task_names)}] {task_name}")

        try:
            # Restart server if needed
            if task_name in NEEDS_SERVER_RESTART:
                restart_mw_server(container_url)

            # Init
            init_task(container_url, task_name, device_id)
            wait_time = 15 if "Mastodon" in task_name or "Mattermost" in task_name else 8
            time.sleep(wait_time)
            wait_adb(adb_serial)

            # Get task goal
            try:
                from ground_truth_cli_finder import http_get as _hget
                goal_resp = _hget(f"{container_url}/task/goal?task_name={task_name}")
                goal = str(goal_resp) if goal_resp else task_name
            except Exception:
                goal = task_name

            # Execute ground truth and time it
            start_time = time.time()
            gt_fn = GROUND_TRUTH[task_name]
            gt_fn(adb_serial, container_url, device_id)
            elapsed = time.time() - start_time

            # Eval
            time.sleep(2)
            score, reason = eval_task(container_url, task_name, device_id)

            # Build trajectory
            # Since we don't instrument individual commands in this mode,
            # create a single-step trajectory with the result
            steps_data = [{
                "action_type": "ground_truth",
                "action_params": {"task_name": task_name, "elapsed_seconds": round(elapsed, 2)},
                "command_output": f"score={score}, reason={reason}",
                "thought": f"Executed ground truth CLI solution for {task_name}",
            }]

            trajectory = make_atif_trajectory(
                task_name=task_name,
                task_goal=goal,
                steps_data=steps_data,
                reward=score,
            )
            trajectories.append(trajectory)
            out.write(json.dumps(trajectory, ensure_ascii=False) + "\n")
            out.flush()

            status = "PASS" if score > 0 else "FAIL"
            print(f"  {status} (score={score}, {reason[:60]})")

            # Teardown
            teardown_task(container_url, task_name, device_id)

        except Exception as e:
            print(f"  ERROR: {e}")
            try:
                teardown_task(container_url, task_name, device_id)
            except Exception:
                pass

    out.close()

    passed = sum(1 for t in trajectories if t["final_metrics"]["reward"] > 0)
    print(f"\nGenerated {len(trajectories)} ATIF trajectories → {output_path}")
    print(f"Passed: {passed}/{len(trajectories)}")
    return trajectories


def main():
    parser = argparse.ArgumentParser(
        description="Generate ATIF trajectories for MobileWorld ground truth",
    )
    parser.add_argument("--results", type=str, default=None,
                        help="Path to ground truth results JSONL (offline mode)")
    parser.add_argument("--live", action="store_true",
                        help="Run live on container and generate trajectories")
    parser.add_argument("--container-url", type=str, default="http://localhost:6809")
    parser.add_argument("--adb-serial", type=str, default="docker:mobile_world_env_5:emulator-5554")
    parser.add_argument("--device-id", type=str, default="emulator-5554")
    parser.add_argument("--container-name", type=str, default="mobile_world_env_5")
    parser.add_argument("--output", type=str, default="gt_atif_trajectories.jsonl")
    args = parser.parse_args()

    if args.results:
        generate_from_results(args.results, args.output)
    elif args.live:
        generate_from_live(
            args.container_url, args.adb_serial, args.device_id,
            args.output, args.container_name,
        )
    else:
        print("Specify --results <file> or --live")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
