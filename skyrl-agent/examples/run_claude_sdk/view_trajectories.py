#!/usr/bin/env python3
"""Launch Harbor Viewer for ATIF trajectories from Claude CLI experiments.

Converts our results layout into Harbor's expected directory structure
(via symlinks) and starts the viewer on a local port.

Usage:
    # View a single experiment
    python view_trajectories.py --results-dir results/ClaudeCodeCLI_claudeopus46_260310_2350

    # View all experiments in results/
    python view_trajectories.py --results-dir results/

    # Custom port
    python view_trajectories.py --results-dir results/ --port 8888
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def _build_trial_result(task_result: dict, job_name: str) -> dict:
    """Build a Harbor TrialResult dict from our task result."""
    task_id = task_result.get("task_id", 0)
    trial_name = f"task_{task_id:03d}"
    reward = task_result.get("reward", 0.0)
    task_text = task_result.get("task", "")
    elapsed = task_result.get("elapsed_seconds", 0)
    error = task_result.get("error")

    now = datetime.now().isoformat()

    result = {
        "id": str(uuid4()),
        "task_name": task_text[:80] or f"task_{task_id}",
        "trial_name": trial_name,
        "trial_uri": trial_name,
        "task_id": {"path": f"task_{task_id:03d}"},
        "source": "android_world",
        "task_checksum": f"task_{task_id}_seed_{task_result.get('seed', 0)}",
        "config": {
            "task": {
                "name": task_text[:80] or f"task_{task_id}",
                "path": f"task_{task_id:03d}",
                "id": {"path": f"task_{task_id:03d}"},
                "source": "android_world",
            },
            "trial_name": trial_name,
            "trials_dir": ".",
            "timeout_multiplier": 1.0,
            "agent": {
                "name": "ClaudeCodeCLI",
                "model_name": "claude-opus-4-6",
            },
            "environment": {"type": "docker"},
            "verifier": {"type": "android_world"},
            "artifacts": [],
        },
        "agent_info": {
            "name": "ClaudeCodeCLI",
            "version": "1.0",
            "model_info": {
                "name": "claude-opus-4-6",
                "provider": "anthropic",
            },
        },
        "verifier_result": {
            "rewards": {"reward": reward},
        },
        "started_at": now,
        "finished_at": now,
    }

    if error:
        result["exception_info"] = {
            "exception_type": "RuntimeError",
            "exception_message": error,
            "exception_traceback": "",
            "occurred_at": now,
        }

    return result


def _build_job_result(trial_results: list[dict]) -> dict:
    """Build a Harbor JobResult dict."""
    return {
        "id": str(uuid4()),
        "started_at": datetime.now().isoformat(),
        "finished_at": datetime.now().isoformat(),
        "n_total_trials": len(trial_results),
        "stats": {
            "n_trials": len(trial_results),
            "n_errors": sum(1 for t in trial_results if t.get("exception_info")),
            "evals": {},
        },
        "trial_results": trial_results,
    }


def prepare_viewer_dir(results_dirs: list[Path], viewer_dir: Path):
    """Convert our results layout into Harbor's expected structure.

    Our layout:
        results/{exp_name}/results.jsonl
        results/{exp_name}/atif_trajectories/task_003.json

    Harbor expects:
        viewer_dir/{job_name}/{trial_name}/result.json
        viewer_dir/{job_name}/{trial_name}/agent/trajectory.json
        viewer_dir/{job_name}/result.json
    """
    for results_dir in results_dirs:
        results_jsonl = results_dir / "results.jsonl"
        atif_dir = results_dir / "atif_trajectories"

        if not results_jsonl.exists():
            print(f"  Skipping {results_dir.name}: no results.jsonl")
            continue

        job_name = results_dir.name
        job_dir = viewer_dir / job_name
        job_dir.mkdir(parents=True, exist_ok=True)

        # Load task results
        task_results = []
        with open(results_jsonl) as f:
            for line in f:
                if line.strip():
                    task_results.append(json.loads(line))

        # Create trial directories with result.json and trajectory symlink
        trial_result_dicts = []
        for task_result in task_results:
            task_id = task_result.get("task_id", 0)
            trial_name = f"task_{task_id:03d}"

            trial_dir = job_dir / trial_name
            trial_dir.mkdir(exist_ok=True)

            # Write trial result.json
            trial_result = _build_trial_result(task_result, job_name)
            trial_result_dicts.append(trial_result)
            with open(trial_dir / "result.json", "w") as f:
                json.dump(trial_result, f, indent=2, default=str)

            # Symlink trajectory
            agent_dir = trial_dir / "agent"
            agent_dir.mkdir(exist_ok=True)
            traj_src = atif_dir / f"task_{task_id:03d}.json"
            traj_dst = agent_dir / "trajectory.json"
            if traj_src.exists() and not traj_dst.exists():
                traj_dst.symlink_to(traj_src.resolve())

        # Write job-level result.json
        job_result = _build_job_result(trial_result_dicts)
        with open(job_dir / "result.json", "w") as f:
            json.dump(job_result, f, indent=2, default=str)

        solved = sum(1 for t in task_results if t.get("reward", 0) > 0)
        print(f"  {job_name}: {len(task_results)} tasks, {solved} solved")


def main():
    parser = argparse.ArgumentParser(
        description="Launch Harbor Viewer for Claude CLI ATIF trajectories",
    )
    parser.add_argument(
        "--results-dir", required=True,
        help="Path to a single experiment dir or parent dir containing multiple experiments",
    )
    parser.add_argument("--port", type=int, default=8080, help="Port for viewer (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument(
        "--prepare-only", action="store_true",
        help="Only prepare the viewer directory, don't start the server",
    )
    args = parser.parse_args()

    results_path = Path(args.results_dir).resolve()

    # Determine if this is a single experiment or a parent directory
    if (results_path / "results.jsonl").exists():
        # Single experiment
        results_dirs = [results_path]
    else:
        # Parent directory — find all subdirs with results.jsonl
        results_dirs = sorted([
            d for d in results_path.iterdir()
            if d.is_dir() and (d / "results.jsonl").exists()
        ])

    if not results_dirs:
        print(f"No experiments found in {results_path}")
        return 1

    print(f"Found {len(results_dirs)} experiment(s)")

    # Create viewer directory
    viewer_dir = results_path / ".harbor_viewer"
    if (results_path / "results.jsonl").exists():
        # Single experiment — put viewer dir alongside
        viewer_dir = results_path.parent / ".harbor_viewer"
    viewer_dir.mkdir(exist_ok=True)

    print(f"Preparing viewer directory: {viewer_dir}")
    prepare_viewer_dir(results_dirs, viewer_dir)

    if args.prepare_only:
        print(f"\nViewer directory ready at: {viewer_dir}")
        print(f"Start manually: python -c \"from harbor.viewer import create_app; import uvicorn; uvicorn.run(create_app('{viewer_dir}'), host='0.0.0.0', port={args.port})\"")
        return 0

    # Launch Harbor Viewer
    print(f"\nStarting Harbor Viewer on http://{args.host}:{args.port}")
    print(f"Press Ctrl+C to stop.\n")

    from harbor.viewer import create_app
    import uvicorn

    # Locate static frontend files from harbor package
    import harbor.viewer
    static_dir = Path(harbor.viewer.__file__).parent / "static"
    if not static_dir.exists():
        print(f"WARNING: Harbor static files not found at {static_dir}")
        static_dir = None

    app = create_app(viewer_dir, static_dir=static_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    sys.exit(main() or 0)
