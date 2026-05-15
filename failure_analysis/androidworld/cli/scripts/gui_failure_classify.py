"""Classify GUI agent failure trajectories against the 11 bottom-up failure modes
from `failure_analysis/androidworld/cli/discovery/failure_modes.md` (derived from
211 CLI-solvable failures).

Notes:
- GUI agents do not run shell, so several CLI-specific modes (raw_sqlite_write,
  terminus2_command_envelope_misuse, byte_level_content_separator_mismatch,
  wrote_to_wrong_filesystem_directory) likely have ~0% prevalence on GUI.
- The classifier may emit `doesnt_fit_any_mode` with a brief snake_case label,
  which is the honest answer when GUI failures don't fit any CLI-derived mode.

Usage:
  python gui_failure_classify.py --result-dir eval-runners/results/ClaudeCodeCLI_GUIOwl1532BInstruct_260415_0108
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OUT_DIR = REPO / "failure_analysis/androidworld/cli/discovery/gui"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FAILURE_MODES_PATH = REPO / "failure_analysis/androidworld/cli/discovery/failure_modes.md"

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_mode": {"type": "string"},
        "secondary_modes": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "rationale": {"type": "string"},
        "evidence_steps": {"type": "array", "items": {"type": "integer"}},
        "is_gui_specific_pattern": {"type": "boolean"},
    },
    "required": ["primary_mode", "secondary_modes", "confidence", "rationale",
                 "evidence_steps", "is_gui_specific_pattern"],
    "additionalProperties": False,
}

CLASSIFY_SYSTEM_PROMPT = """You are classifying a single failed AndroidWorld GUI-agent trajectory against a fixed taxonomy of 11 failure modes that were derived bottom-up from 211 CLI-agent failures.

The 11 modes are listed in the user prompt. Some are CLI-specific (e.g., `terminus2_command_envelope_misuse`, `raw_sqlite_write_bypassed_app_pipeline`, `byte_level_content_separator_mismatch`) and CANNOT apply to a GUI agent that only emits taps, types, and swipes.

Your job:
1. Pick the SINGLE primary_mode that best matches the failure. Use the exact mode name from the list. If NONE of the 11 modes reasonably fit a GUI-specific pattern, emit `doesnt_fit_any_mode` and set is_gui_specific_pattern=true.
2. List any secondary_modes that also clearly apply (0-3, exact names). Empty array if none.
3. confidence: HIGH if the transcript signature matches obviously, MEDIUM if reasonable, LOW if guessed.
4. rationale: 2-3 sentences citing specific steps. Be specific about what the agent did, not what it should have done.
5. evidence_steps: list of step_idx integers that justify the classification.
6. is_gui_specific_pattern: true ONLY if you chose `doesnt_fit_any_mode` or if the primary mode applies but the failure has a distinctly GUI flavor (e.g., wrong tap target, scroll off-screen) that a CLI-version of the same mode wouldn't have.

Be honest about CLI-only modes: do NOT force-fit a GUI failure into them. Use `doesnt_fit_any_mode` instead."""


def load_failure_modes_text() -> str:
    """Return the failure_modes.md content, trimmed to the relevant section."""
    text = FAILURE_MODES_PATH.read_text()
    # Keep just the failure-modes list section
    m = re.search(r"## Failure modes \(proposed\)(.*?)(?:^---|\Z)", text, re.DOTALL | re.MULTILINE)
    if m:
        return "## Failure modes\n\n" + m.group(1).strip()
    return text


def condense_gui_trajectory(failure_row: dict) -> str:
    """Render a GUI failure into a compact, step-by-step string suitable for the LLM."""
    out = []
    task = failure_row.get("task", "")
    task_id = failure_row.get("task_id")
    step_count = failure_row.get("step_count")
    num_turns = failure_row.get("num_turns")
    finished = failure_row.get("finished")
    last_err = failure_row.get("last_error", "") or ""
    finish_desc = failure_row.get("finish_description", "") or ""

    out.append(f"USER TASK (task_{task_id:03d}): {task}")
    out.append(f"step_count={step_count} num_turns={num_turns} finished={finished}")
    if last_err:
        out.append(f"last_error: {last_err[:500]}")

    cmds = failure_row.get("commands", []) or []
    for c in cmds:
        sidx = c.get("step_idx")
        action = c.get("action", {}) or {}
        action_type = action.get("action_type", "?")
        action_text = (c.get("action_text") or "")[:400]
        # Compact non-text args
        args = {k: v for k, v in action.items()
                if k != "action_type" and k not in ("text",)}
        arg_str = ""
        if args:
            arg_str = " " + " ".join(f"{k}={json.dumps(v)[:120]}" for k, v in args.items())
        text_str = ""
        if "text" in action:
            text_str = f' text={json.dumps(action["text"])[:300]}'
        out.append(f"[step {sidx}] {action_type}{arg_str}{text_str}")
        if action_text:
            out.append(f"           reason: {action_text}")
    if finish_desc:
        out.append(f"[FINISH DESCRIPTION] {finish_desc[:500]}")
    return "\n".join(out)


def call_claude(prompt: str, model: str, effort: str, system_prompt: str,
                schema: dict, timeout: int = 600) -> dict:
    cmd = [
        "claude", "--print",
        "--model", model,
        "--effort", effort,
        "--output-format", "json",
        "--system-prompt", system_prompt,
        "--json-schema", json.dumps(schema),
        "--dangerously-skip-permissions",
    ]
    LARGE = 100_000
    if len(prompt) < LARGE:
        cmd.append(prompt)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    else:
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exit {result.returncode}: {result.stderr[:500]}")
    envelope = json.loads(result.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude error: {envelope.get('result', '')[:300]}")
    structured = envelope.get("structured_output")
    if structured is not None:
        return structured
    raw = envelope.get("result") or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"no parseable JSON: {raw[:300]}")


def classify_one(failure_row: dict, modes_text: str, agent_class: str, model: str,
                 model_id: str, effort: str) -> dict:
    traj_text = condense_gui_trajectory(failure_row)
    prompt = f"""# TRAJECTORY METADATA

Agent: {agent_class}
Model: {model}
Task ID: task_{failure_row.get('task_id'):03d}

# THE 11 FAILURE MODES (derived from 211 CLI-agent failures)

{modes_text}

# TRAJECTORY

{traj_text}

# YOUR TASK

Classify this GUI-agent failure per the system prompt's instructions. Output JSON matching the provided schema."""
    t0 = time.time()
    out = call_claude(prompt, model=model_id, effort=effort,
                      system_prompt=CLASSIFY_SYSTEM_PROMPT, schema=CLASSIFY_SCHEMA)
    dt = time.time() - t0
    return {
        "task_id": failure_row.get("task_id"),
        "task_name": failure_row.get("task"),
        "agent_class": agent_class,
        "model": model,
        "step_count": failure_row.get("step_count"),
        "finished": failure_row.get("finished"),
        "elapsed_sec": round(dt, 1),
        **out,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result-dir", required=True, help="Path to a result run dir containing results.jsonl")
    ap.add_argument("--agent-class", default=None)
    ap.add_argument("--model", default=None, help="Display name for the model under test")
    ap.add_argument("--model-id", default="opus", help="Claude model ID for the judge")
    ap.add_argument("--effort", default="max")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--output", default=None, help="Output JSONL path. Defaults to gui/<run>.jsonl")
    args = ap.parse_args()

    rd = Path(args.result_dir)
    if not rd.is_absolute():
        rd = REPO / rd
    if not (rd / "results.jsonl").exists():
        print(f"ERROR: no results.jsonl in {rd}"); sys.exit(1)

    # Parse run name for default agent_class / model
    parts = rd.name.split("_")
    agent_class = args.agent_class or parts[0]
    model = args.model or (parts[1] if len(parts) > 1 else "?")

    rows = [json.loads(l) for l in (rd / "results.jsonl").read_text().splitlines() if l.strip()]
    fails = [r for r in rows if not (r.get("reward", 0) > 0 or r.get("success"))]
    print(f"Run: {rd.name}")
    print(f"Total tasks: {len(rows)}, failures: {len(fails)}")

    output_path = Path(args.output) if args.output else OUT_DIR / f"{rd.name}.jsonl"
    if not output_path.is_absolute():
        output_path = REPO / output_path

    modes_text = load_failure_modes_text()
    print(f"Classifying {len(fails)} failures | model={args.model_id} effort={args.effort} workers={args.workers}")
    print(f"Output: {output_path.relative_to(REPO)}")

    success = 0; fail = 0
    output_path.write_text("")  # truncate
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(classify_one, r, modes_text, agent_class, model,
                              args.model_id, args.effort): r for r in fails}
        for i, fut in enumerate(as_completed(futures), 1):
            r = futures[fut]
            try:
                res = fut.result()
                with output_path.open("a") as f:
                    f.write(json.dumps(res) + "\n")
                success += 1
                print(f"  [{i}/{len(fails)}] task_{r.get('task_id'):03d} → {res['primary_mode']} ({res['confidence']}) [{res['elapsed_sec']}s]")
            except Exception as e:
                fail += 1
                print(f"  [{i}/{len(fails)}] ERR task_{r.get('task_id'):03d}: {type(e).__name__}: {str(e)[:120]}")
    print(f"\nDone: {success} ok, {fail} failed. Output: {output_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
