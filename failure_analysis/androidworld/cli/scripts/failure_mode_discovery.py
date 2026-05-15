"""Bottom-up failure-mode discovery using Claude Code CLI at max reasoning effort.

Two phases:
  1. Summarize each of 211 readable failures (one Claude CLI call per trajectory,
     opus 4.7 --effort max). Output: summaries.jsonl
  2. Propose 5-12 failure mode categories from all summaries in one final call
     (opus 4.7 --effort max). Output: failure_modes.md

No Docent. No v2 rubric vocabulary. Pure bottom-up from the data.

Usage:
  python failure_mode_discovery.py --phase summarize --workers 4
  python failure_mode_discovery.py --phase propose
  python failure_mode_discovery.py  # runs both
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "failure_analysis/androidworld/cli"))

DATA_DIR = REPO / "failure_analysis/androidworld/cli/data"
OUT_DIR = REPO / "failure_analysis/androidworld/cli/discovery"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARIES_PATH = OUT_DIR / "summaries.jsonl"
FAILURE_MODES_PATH = OUT_DIR / "failure_modes.md"
PROPOSE_RAW_PATH = OUT_DIR / "propose_raw.json"

# Schema for the summarize step
SUMMARIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "agent_behavior_pattern": {"type": "string"},
        "what_blocked_success": {"type": "string"},
    },
    "required": ["root_cause", "agent_behavior_pattern", "what_blocked_success"],
    "additionalProperties": False,
}

# Schema for the propose-modes step
PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "failure_modes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "transcript_signature": {"type": "string"},
                    "estimated_prevalence_pct": {"type": "number"},
                },
                "required": ["name", "description", "transcript_signature", "estimated_prevalence_pct"],
                "additionalProperties": False,
            },
        },
        "overarching_observations": {"type": "string"},
    },
    "required": ["failure_modes", "overarching_observations"],
    "additionalProperties": False,
}


def parse_gui_only_ids() -> set[int]:
    text = (REPO / "docs/final/AndroidWorld2026/androidworld_ground_truth_reference_v2.md").read_text()
    gui = set(); cur = None
    for ln in text.splitlines():
        m = re.match(r"###\s+Task\s+0?(\d+):", ln)
        if m: cur = int(m.group(1)); continue
        if cur is not None and re.match(r"\*\*Status:\*\*\s*GUI-only", ln):
            gui.add(cur); cur = None
        elif cur is not None and ln.startswith("**Status:**"):
            cur = None
    return gui


def condense_trajectory(traj_path: Path) -> str:
    """Same format as judge_runner.condense_trajectory — preserves all steps + observations."""
    raw = json.loads(traj_path.read_text())
    out = []
    if raw.get("schema_version", "").startswith("ATIF-"):
        for s in raw.get("steps", []):
            src = s.get("source"); msg = (s.get("message") or "")
            if src == "system":
                out.append(f"[SYSTEM PROMPT: {len(msg)} chars elided]"); continue
            if src == "user":
                out.append(f"USER TASK: {msg}"); continue
            sid = s.get("step_id", 0)
            obs = s.get("observation")
            obs_str = ""
            if obs:
                obs_text = obs if isinstance(obs, str) else json.dumps(obs)
                m = re.search(r'"content":\s*"((?:[^"\\]|\\.)*)"', obs_text)
                if m:
                    obs_str = m.group(1).encode().decode("unicode_escape", errors="ignore")[:1500]
                else:
                    obs_str = obs_text[:1500]
            out.append(f"[step {sid}] AGENT: {msg[:1200]}")
            if obs_str:
                out.append(f"           OBS: {obs_str}")
    elif "messages" in raw:
        for i, m in enumerate(raw["messages"]):
            role = m.get("role"); content = m.get("content") or ""
            if role == "system":
                out.append(f"[SYSTEM PROMPT: {len(content)} chars elided]"); continue
            if role == "user" and i == 1:
                out.append(f"USER TASK: {content}"); continue
            if role == "assistant":
                out.append(f"[msg {i}] AGENT: {content[:1500]}")
            elif role == "user":
                out.append(f"          OBS: {content[:1500]}")
        sub = (raw.get("info") or {}).get("submission")
        if sub:
            out.append(f"\n[SUBMISSION] {sub}")
    return "\n".join(out)


SUMMARIZE_SYSTEM_PROMPT = """You are reviewing a single failed AndroidWorld CLI agent run.

AndroidWorld is a benchmark of Android tasks (calendar, SMS, file ops, music apps, expense apps, system settings, etc.) that the agent solves via `adb shell` commands — no screen interaction, no taps. The agent fails when its actions don't produce the device state the verifier expects.

Your job: write a focused 2-3 sentence summary of the ROOT CAUSE of failure in the agent's behavior. Use Android-specific vocabulary where it helps.

You MUST output JSON matching the provided schema. Fields:
- root_cause: 1-2 sentences pinpointing the specific cause of failure
- agent_behavior_pattern: 1 sentence describing the *behavioral pattern* the agent exhibited (what was it doing that led to failure)
- what_blocked_success: 1 sentence describing what specific thing prevented success (e.g., "wrote to mmssms.db but eval reads via content://sms provider")

Be SPECIFIC. Cite step numbers when useful. Focus on agent BEHAVIORS and Android system interactions, not the task itself.

Bad: "The SMS task failed because SMS is hard."
Good: "The agent inserted a row directly into mmssms.db (step 12) without temporarily setting com.android.shell as the default SMS app, so the SmsProvider silently rejected the insert and the eval's content://sms query returned no row."

Avoid using existing rubric leaf names ('weak verification', 'step repetition', 'disobey specification', etc.). Describe the behavior in your own words."""


def call_claude(prompt: str, model: str, effort: str, system_prompt: str, schema: dict, timeout: int = 600) -> dict:
    """Invoke Claude Code CLI with max reasoning, return parsed structured output.
    Large prompts go via stdin to avoid the OS argv length limit."""
    cmd = [
        "claude", "--print",
        "--model", model,
        "--effort", effort,
        "--output-format", "json",
        "--system-prompt", system_prompt,
        "--json-schema", json.dumps(schema),
        "--dangerously-skip-permissions",
    ]
    # If prompt is small enough, pass as argv; else stdin.
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
    try: return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"no parseable JSON: {raw[:300]}")


def summarize_one(row: dict, model: str, effort: str) -> dict:
    traj_path = REPO / row["traj_path"]
    traj_text = condense_trajectory(traj_path)
    prompt = f"""# TRAJECTORY METADATA

Task ID: {row['task_id']}
Task description: {row.get('task_name', '')}
Agent: {row['agent_class']}
Model: {row.get('model_short', '?')}
Steps used / max: {row.get('step_count')} / {row.get('max_turns')}

# TRAJECTORY

{traj_text}

# YOUR TASK

Summarize the root cause of this failure per the system prompt's instructions. Output JSON."""
    t0 = time.time()
    out = call_claude(prompt, model=model, effort=effort,
                      system_prompt=SUMMARIZE_SYSTEM_PROMPT, schema=SUMMARIZE_SCHEMA)
    dt = time.time() - t0
    return {
        "trajectory_id": row["trajectory_id"],
        "task_id": row["task_id"],
        "agent_class": row["agent_class"],
        "task_name": row.get("task_name"),
        "elapsed_sec": round(dt, 1),
        **out,
    }


def load_done(path: Path) -> set[str]:
    if not path.exists(): return set()
    return {json.loads(l)["trajectory_id"] for l in path.read_text().splitlines() if l.strip()}


def run_summarize(args):
    rows = [json.loads(l) for l in (DATA_DIR / "pilot_set.jsonl").read_text().splitlines() if l.strip()]
    gui = parse_gui_only_ids()
    rows = [r for r in rows if r["task_id"] not in gui]
    done = load_done(SUMMARIES_PATH) if args.resume else set()
    rows = [r for r in rows if r["trajectory_id"] not in done]
    if args.limit: rows = rows[:args.limit]
    print(f"Summarizing {len(rows)} trajectories (already done: {len(done)}) | model={args.model} effort={args.effort} workers={args.workers}")
    success = 0; fail = 0
    if args.workers <= 1:
        for i, r in enumerate(rows, 1):
            try:
                res = summarize_one(r, args.model, args.effort)
                with SUMMARIES_PATH.open("a") as f: f.write(json.dumps(res) + "\n")
                success += 1
                print(f"  [{i}/{len(rows)}] {r['trajectory_id']} [{res['elapsed_sec']}s]")
            except Exception as e:
                fail += 1
                print(f"  [{i}/{len(rows)}] ERR {r['trajectory_id']}: {type(e).__name__}: {str(e)[:120]}")
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(summarize_one, r, args.model, args.effort): r for r in rows}
            for i, fut in enumerate(as_completed(futures), 1):
                r = futures[fut]
                try:
                    res = fut.result()
                    with SUMMARIES_PATH.open("a") as f: f.write(json.dumps(res) + "\n")
                    success += 1
                    print(f"  [{i}/{len(rows)}] {r['trajectory_id']} [{res['elapsed_sec']}s]")
                except Exception as e:
                    fail += 1
                    print(f"  [{i}/{len(rows)}] ERR {r['trajectory_id']}: {type(e).__name__}: {str(e)[:120]}")
    print(f"\nSummarize done: {success} ok, {fail} failed. Output: {SUMMARIES_PATH.relative_to(REPO)}")


PROPOSE_SYSTEM_PROMPT = """You are reviewing failure summaries from AndroidWorld CLI agent runs across multiple agents and models. All summaries describe failed runs.

Your job: propose 5-12 MUTUALLY EXCLUSIVE failure-mode categories that capture the distinct BEHAVIORS that caused these runs to fail.

Quality bar for categories:
- Specific enough that a researcher reading it could imagine a concrete prompt-engineering fix, training-data change, or harness intervention.
- About the AGENT'S BEHAVIOR, not the task type or app. "SMS tasks failed" is not a category. "Agent writes to mmssms.db without setting com.android.shell as default SMS app, so SmsProvider rejects the write" IS a category.
- Mutually exclusive: a typical failure should clearly fit ONE category most.
- Collectively exhaustive of what you saw — every summary should be classifiable.

Do not echo existing taxonomy vocabulary like 'weak verification', 'step repetition', 'context loss', or 'disobey specification'. Describe categories in your own behavioral terms.

For each category, output:
- name: short snake_case identifier
- description: 1-3 sentence specific behavior pattern
- transcript_signature: one-sentence description of a tell-tale transcript pattern
- estimated_prevalence_pct: rough percentage of the input summaries you'd assign to this category

Also output an overarching_observations field: 2-3 sentences on what stood out across all 211 summaries (model differences, agent-class patterns, surprising shared failure modes, etc.).

Output JSON matching the schema."""


def run_propose(args):
    if not SUMMARIES_PATH.exists():
        print(f"ERROR: {SUMMARIES_PATH.relative_to(REPO)} not found. Run --phase summarize first.")
        sys.exit(1)
    summaries = [json.loads(l) for l in SUMMARIES_PATH.read_text().splitlines() if l.strip()]
    print(f"Loaded {len(summaries)} summaries. Building propose prompt...")

    # Compact one-line per summary so we can fit all 211 in one prompt
    lines = []
    for s in summaries:
        lines.append(
            f"#{s['task_id']:>3d} [{s['agent_class']:<13s}] "
            f"ROOT: {s['root_cause']} | PATTERN: {s['agent_behavior_pattern']} | BLOCK: {s['what_blocked_success']}"
        )
    summaries_block = "\n\n".join(lines)
    prompt = f"""# 211 failure summaries

Below are root-cause summaries from {len(summaries)} failed AndroidWorld CLI agent runs across 3 agent harnesses (ClaudeCodeCLI, MiniSweAgent, Terminus2) × 6 model combos. All runs are failures (reward=0).

{summaries_block}

# YOUR TASK

Propose 5-12 mutually exclusive failure-mode categories that capture the distinct behaviors observed. Output JSON per the system prompt's instructions."""

    print(f"Prompt size: {len(prompt):,} chars")
    print(f"Calling Claude {args.model} effort={args.effort}...")
    t0 = time.time()
    out = call_claude(prompt, model=args.model, effort=args.effort,
                      system_prompt=PROPOSE_SYSTEM_PROMPT, schema=PROPOSE_SCHEMA, timeout=1800)
    dt = time.time() - t0
    print(f"Done in {dt:.0f}s. Proposed {len(out['failure_modes'])} failure modes.")

    PROPOSE_RAW_PATH.write_text(json.dumps(out, indent=2))
    print(f"Raw output saved: {PROPOSE_RAW_PATH.relative_to(REPO)}")

    md = []
    md.append(f"# Bottom-Up Failure Modes — Claude Opus 4.7 (max effort)")
    md.append("")
    md.append(f"**Method:** 2-phase Claude Code CLI pipeline, no Docent, no v2-rubric anchoring.")
    md.append(f"**Pool:** {len(summaries)} CLI-solvable readable failures, 3 agent classes × 6 model combos.")
    md.append(f"**Phase 1:** {len(summaries)} per-trajectory root-cause summaries (Claude opus-4-7 max effort).")
    md.append(f"**Phase 2:** 1 synthesis call over all summaries (Claude opus-4-7 max effort, {dt:.0f}s).")
    md.append("")
    md.append(f"## Overarching observations\n\n{out['overarching_observations']}\n")
    md.append("## Failure modes (proposed)\n")
    for i, m in enumerate(out["failure_modes"], 1):
        md.append(f"### {i}. `{m['name']}` (~{m['estimated_prevalence_pct']:.0f}%)\n")
        md.append(f"**Description:** {m['description']}\n")
        md.append(f"**Transcript signature:** {m['transcript_signature']}\n")
    md.append("\n---")
    md.append(f"\nGenerated at {time.strftime('%Y-%m-%d %H:%M:%S')}.")

    FAILURE_MODES_PATH.write_text("\n".join(md))
    print(f"Wrote failure modes markdown: {FAILURE_MODES_PATH.relative_to(REPO)}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["summarize", "propose", "both"], default="both")
    p.add_argument("--model", default="opus")
    p.add_argument("--effort", default="max")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--resume", action="store_true", default=True)
    args = p.parse_args()
    if args.phase in ("summarize", "both"):
        run_summarize(args)
    if args.phase in ("propose", "both"):
        run_propose(args)


if __name__ == "__main__":
    main()
