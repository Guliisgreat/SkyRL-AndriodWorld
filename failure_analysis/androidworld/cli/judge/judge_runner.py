"""Run the LLM judge over readable failures using Claude Code CLI.

Usage:
    # Test on first N trajectories
    python judge_runner.py --limit 10

    # Run on all CLI-solvable readable failures (~213)
    python judge_runner.py

    # Custom model / effort
    python judge_runner.py --model opus --effort max

    # Parallel
    python judge_runner.py --workers 4

Outputs:
    judge/outputs/judge_results.jsonl   one row per trajectory (primary_leaf, secondaries, etc)
    judge/outputs/judge_errors.jsonl    rows that failed to classify
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
JUDGE_DIR = REPO / "failure_analysis/androidworld/cli/judge"
DATA_DIR = REPO / "failure_analysis/androidworld/cli/data"
RUBRIC_PATH = REPO / "failure_analysis/androidworld/cli/rubric/rubric_v2.md"
SYSTEM_PROMPT_PATH = JUDGE_DIR / "prompts/system_v2.md"
OUTPUT_PATH = JUDGE_DIR / "outputs/judge_results_v2.jsonl"
ERROR_PATH = JUDGE_DIR / "outputs/judge_errors_v2.jsonl"


# JSON schema constraint for Claude's output
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_leaf": {"type": "string"},
        "secondary_leaves": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "rationale": {"type": "string"},
        "evidence_step_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["primary_leaf", "secondary_leaves", "confidence", "rationale", "evidence_step_ids"],
    "additionalProperties": False,
}


def parse_gui_only_ids() -> set[int]:
    text = (REPO / "docs/final/AndroidWorld2026/androidworld_ground_truth_reference_v2.md").read_text()
    gui = set()
    cur = None
    for ln in text.splitlines():
        m = re.match(r"###\s+Task\s+0?(\d+):", ln)
        if m:
            cur = int(m.group(1))
            continue
        if cur is not None and re.match(r"\*\*Status:\*\*\s*GUI-only", ln):
            gui.add(cur); cur = None
        elif cur is not None and ln.startswith("**Status:**"):
            cur = None
    return gui


def condense_trajectory(traj_path: Path) -> str:
    """Format trajectory for the judge."""
    raw = json.loads(traj_path.read_text())
    out = []
    if raw.get("schema_version", "").startswith("ATIF-"):
        for s in raw.get("steps", []):
            src = s.get("source")
            msg = s.get("message") or ""
            if src == "system":
                out.append(f"[step {s.get('step_id', 0)}] SYSTEM: {msg[:300]}{'...' if len(msg) > 300 else ''}")
                continue
            if src == "user":
                out.append(f"[step {s.get('step_id', 0)}] USER TASK: {msg}")
                continue
            sid = s.get("step_id", 0)
            cmd = msg
            obs = s.get("observation")
            obs_text = ""
            if obs:
                obs_text = obs if isinstance(obs, str) else json.dumps(obs)
                m = re.search(r'"content":\s*"([^"]*)"', obs_text)
                if m:
                    obs_text = m.group(1).replace("\\n", "\n")[:1500]
                else:
                    obs_text = obs_text[:1500]
            out.append(f"[step {sid}] AGENT: {cmd}")
            if obs_text:
                out.append(f"           OBSERVATION: {obs_text}")
    elif "messages" in raw:
        for i, m in enumerate(raw["messages"]):
            role = m.get("role")
            content = m.get("content") or ""
            if role == "system":
                out.append(f"[msg {i}] SYSTEM: {content[:300]}{'...' if len(content) > 300 else ''}")
                continue
            if role == "user" and i == 1:
                out.append(f"[msg {i}] USER TASK: {content}")
                continue
            if role == "assistant":
                out.append(f"[msg {i}] AGENT: {content[:2000]}{'...' if len(content) > 2000 else ''}")
            elif role == "user":
                out.append(f"[msg {i}] OBSERVATION: {content[:1500]}{'...' if len(content) > 1500 else ''}")
        sub = (raw.get("info") or {}).get("submission")
        if sub:
            out.append(f"\n[SUBMISSION] {sub}")
    return "\n".join(out)


def build_user_prompt(trajectory_id: str, agent_class: str, model_short: str,
                      task_id: int, task_name: str, max_turns: int,
                      step_count: int, finished: bool, traj_text: str) -> str:
    rubric = RUBRIC_PATH.read_text()
    return f"""# RUBRIC

{rubric}

---

# TRAJECTORY TO CLASSIFY

**Trajectory ID:** {trajectory_id}
**Agent class:** {agent_class}
**Model:** {model_short}
**Task ID:** {task_id} (max_turns={max_turns}, agent stopped at step {step_count}, finished={finished})
**Task description:** {task_name}

## Step-by-step trace

{traj_text}

---

Classify this trajectory's failure mode against the rubric. Output the JSON object as instructed in the system prompt."""


def call_judge(prompt: str, model: str, effort: str, timeout: int = 600) -> dict:
    """Invoke Claude Code CLI in print mode and parse JSON response."""
    cmd = [
        "claude",
        "--print",
        "--model", model,
        "--effort", effort,
        "--output-format", "json",
        "--system-prompt", SYSTEM_PROMPT_PATH.read_text(),
        "--json-schema", json.dumps(JUDGE_SCHEMA),
        "--dangerously-skip-permissions",
        prompt,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI returned {result.returncode}: {result.stderr[:500]}")
    # output-format json + --json-schema → structured output is in envelope["structured_output"]
    envelope = json.loads(result.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI error: {envelope.get('result', '')[:300]}")
    structured = envelope.get("structured_output")
    if structured is not None:
        return structured
    # Fallback: try to parse result as JSON or extract from code fence
    raw = envelope.get("result") or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        raise RuntimeError(f"no parseable JSON in claude output: {raw[:300]}")


def process_one(row: dict, model: str, effort: str) -> dict:
    p = REPO / row["traj_path"]
    traj_text = condense_trajectory(p)
    user_prompt = build_user_prompt(
        trajectory_id=row["trajectory_id"],
        agent_class=row["agent_class"],
        model_short=row.get("model_short", "?"),
        task_id=row["task_id"],
        task_name=row.get("task_name", ""),
        max_turns=row.get("max_turns", 0),
        step_count=row.get("step_count", 0),
        finished=row.get("finished", False),
        traj_text=traj_text,
    )
    t0 = time.time()
    judge = call_judge(user_prompt, model=model, effort=effort)
    dt = time.time() - t0
    return {
        "trajectory_id": row["trajectory_id"],
        "config": row["config"],
        "agent_class": row["agent_class"],
        "task_id": row["task_id"],
        "task_name": row.get("task_name"),
        "judge_model": model,
        "effort": effort,
        "elapsed_sec": round(dt, 1),
        "primary_leaf": judge["primary_leaf"],
        "secondary_leaves": judge["secondary_leaves"],
        "confidence": judge["confidence"],
        "rationale": judge["rationale"],
        "evidence_step_ids": judge["evidence_step_ids"],
    }


def load_done_ids(path: Path) -> set[str]:
    if not path.exists(): return set()
    return {json.loads(l)["trajectory_id"] for l in path.read_text().splitlines() if l.strip()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="Stop after N trajectories")
    p.add_argument("--model", default="opus", help="Model alias for --model")
    p.add_argument("--effort", default="max", choices=["low","medium","high","xhigh","max"])
    p.add_argument("--workers", type=int, default=1, help="Parallel workers")
    p.add_argument("--cli-solvable-only", action="store_true", default=True)
    p.add_argument("--task-id", type=int, default=None, help="Process only this single task_id (any matching config)")
    p.add_argument("--resume", action="store_true", default=True, help="Skip trajectories already in output")
    p.add_argument("--output", default=str(OUTPUT_PATH), help="Output JSONL path")
    args = p.parse_args()

    rows = [json.loads(l) for l in (DATA_DIR / "pilot_set.jsonl").read_text().splitlines()]

    if args.cli_solvable_only:
        gui = parse_gui_only_ids()
        rows = [r for r in rows if r["task_id"] not in gui]

    if args.task_id is not None:
        rows = [r for r in rows if r["task_id"] == args.task_id]

    if args.resume:
        done = load_done_ids(Path(args.output))
        rows = [r for r in rows if r["trajectory_id"] not in done]
        print(f"Resuming: {len(done)} already done, {len(rows)} remaining")

    if args.limit:
        rows = rows[:args.limit]

    print(f"Processing {len(rows)} trajectories with {args.model} effort={args.effort}, workers={args.workers}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    success, fail = 0, 0
    if args.workers <= 1:
        for i, r in enumerate(rows, 1):
            try:
                res = process_one(r, args.model, args.effort)
                with out_path.open("a") as f:
                    f.write(json.dumps(res) + "\n")
                success += 1
                print(f"  [{i}/{len(rows)}] {r['trajectory_id']}: {res['primary_leaf']} (+{len(res['secondary_leaves'])}) [{res['elapsed_sec']}s]")
            except Exception as e:
                fail += 1
                err = {"trajectory_id": r["trajectory_id"], "error": str(e)[:500]}
                with ERROR_PATH.open("a") as f:
                    f.write(json.dumps(err) + "\n")
                print(f"  [{i}/{len(rows)}] {r['trajectory_id']}: ERROR {type(e).__name__}: {str(e)[:120]}")
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(process_one, r, args.model, args.effort): r for r in rows}
            for i, fut in enumerate(as_completed(futures), 1):
                r = futures[fut]
                try:
                    res = fut.result()
                    with out_path.open("a") as f:
                        f.write(json.dumps(res) + "\n")
                    success += 1
                    print(f"  [{i}/{len(rows)}] {r['trajectory_id']}: {res['primary_leaf']} (+{len(res['secondary_leaves'])}) [{res['elapsed_sec']}s]")
                except Exception as e:
                    fail += 1
                    err = {"trajectory_id": r["trajectory_id"], "error": str(e)[:500]}
                    with ERROR_PATH.open("a") as f:
                        f.write(json.dumps(err) + "\n")
                    print(f"  [{i}/{len(rows)}] {r['trajectory_id']}: ERROR {type(e).__name__}: {str(e)[:120]}")

    print()
    print(f"Done: {success} succeeded, {fail} failed")
    print(f"Output: {out_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
