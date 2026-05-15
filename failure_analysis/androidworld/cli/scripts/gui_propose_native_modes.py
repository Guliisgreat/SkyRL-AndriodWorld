"""Second-stage synthesis: from all GUI classification rationales (especially
`doesnt_fit_any_mode` ones), propose 5-8 GUI-native failure modes via a single
Opus max-effort call.

Usage:
  python gui_propose_native_modes.py
"""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
GUI_DIR = REPO / "failure_analysis/androidworld/cli/discovery/gui"
OUT_PATH = GUI_DIR / "gui_native_modes.md"
RAW_PATH = GUI_DIR / "gui_native_modes_raw.json"

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
                    "applies_to_agents": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "description", "transcript_signature",
                             "estimated_prevalence_pct", "applies_to_agents"],
                "additionalProperties": False,
            },
        },
        "overarching_observations": {"type": "string"},
        "cli_modes_that_also_appear_on_gui": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["failure_modes", "overarching_observations",
                 "cli_modes_that_also_appear_on_gui"],
    "additionalProperties": False,
}

PROPOSE_SYSTEM = """You are reviewing AndroidWorld GUI-agent failure classifications.

Each input row is the LLM judge's verdict on a single failed GUI run, against an 11-mode taxonomy derived from CLI agents. Many rows have primary_mode = doesnt_fit_any_mode (because GUI failures often don't match CLI patterns); others were forced into the closest CLI mode.

Your job: propose 5-8 MUTUALLY EXCLUSIVE failure-mode categories that describe the GUI-native behaviors in this data. These should be GUI-specific (taps, swipes, screen reads), not abstract CLI-style categories. Include:
- name: short snake_case identifier
- description: 2-3 sentence specific GUI behavior pattern
- transcript_signature: a tell-tale transcript signature (e.g., "same (x,y) tapped 5+ times in a row", "action_type=answer issued at step ≤2 with hard-coded literal", "swipe action emitted only once when slider requires multi-step swipe")
- estimated_prevalence_pct: rough percentage of input rows
- applies_to_agents: list of agent names (e.g., "GUIOwl15", "qwen3vl32b") if pattern is agent-specific

Also output:
- overarching_observations: 2-3 sentences across both agents
- cli_modes_that_also_appear_on_gui: list of mode names from the CLI 11 that DID match real GUI failures (e.g., intent_launch_treated_as_persistence, reconnaissance_burnout_no_mutation, fabricated_values_after_failed_or_truncated_read)

Output JSON matching the schema."""


def call_claude(prompt: str, system: str, schema: dict, model: str = "opus",
                effort: str = "max", timeout: int = 900) -> dict:
    cmd = [
        "claude", "--print",
        "--model", model,
        "--effort", effort,
        "--output-format", "json",
        "--system-prompt", system,
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
        raise RuntimeError(f"claude exit {result.returncode}: {result.stderr[:500]}")
    env = json.loads(result.stdout)
    if env.get("is_error"):
        raise RuntimeError(f"claude error: {env.get('result', '')[:300]}")
    structured = env.get("structured_output")
    if structured is not None:
        return structured
    raw = env.get("result", "")
    return json.loads(raw)


def main():
    files = sorted(GUI_DIR.glob("*.jsonl"))
    if not files:
        print("No classification files. Run gui_failure_classify.py first."); sys.exit(1)

    lines = []
    counts = {}
    for f in files:
        rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        counts[f.name] = len(rows)
        for r in rows:
            lines.append(json.dumps({
                "agent": r.get("agent_class"),
                "model": r.get("model"),
                "task_id": r.get("task_id"),
                "task": r.get("task_name", "")[:200],
                "primary": r.get("primary_mode"),
                "secondary": r.get("secondary_modes"),
                "gui_specific": r.get("is_gui_specific_pattern"),
                "rationale": r.get("rationale"),
            }))
    print(f"Loaded {len(lines)} classifications: {counts}")

    prompt = f"""# GUI CLASSIFICATION RESULTS

Total: {len(lines)} failed GUI-agent runs across {len(files)} runs.

Each line is one classification verdict (primary mode, secondary modes, rationale):

{chr(10).join(lines)}

# YOUR TASK

Propose 5-8 GUI-native failure modes as instructed in the system prompt. Output JSON."""

    print(f"Prompt size: {len(prompt)} chars. Calling Opus max effort...")
    t0 = time.time()
    out = call_claude(prompt, PROPOSE_SYSTEM, PROPOSE_SCHEMA)
    print(f"Done in {time.time() - t0:.1f}s")
    RAW_PATH.write_text(json.dumps(out, indent=2))

    # Render to markdown
    md = ["# GUI-Native Failure Modes\n"]
    md.append(f"**Method:** Opus 4.7 max-effort synthesis of {len(lines)} GUI classifications "
              f"(across {len(files)} runs: {list(counts.values())}).\n")
    md.append(f"## Overarching observations\n\n{out['overarching_observations']}\n")
    md.append(f"## CLI modes that also appear on GUI\n")
    for m in out.get("cli_modes_that_also_appear_on_gui", []):
        md.append(f"- `{m}`")
    md.append("\n## GUI-native modes\n")
    for i, m in enumerate(out["failure_modes"], 1):
        md.append(f"### {i}. `{m['name']}` (~{m['estimated_prevalence_pct']}%)\n")
        md.append(f"**Description:** {m['description']}\n")
        md.append(f"**Transcript signature:** {m['transcript_signature']}\n")
        if m.get("applies_to_agents"):
            md.append(f"**Applies to agents:** {', '.join(m['applies_to_agents'])}\n")
    OUT_PATH.write_text("\n".join(md))
    print(f"Wrote: {OUT_PATH.relative_to(REPO)}")
    print(f"Raw  : {RAW_PATH.relative_to(REPO)}")


if __name__ == "__main__":
    main()
