"""Sample 15 trajectories for two-annotator validation of the v2 rubric.

Strategy:
- Stratified across v2 primary leaves (so the validation covers all of v2's categories)
- Spread across 6 agent×model combos (no agent bias)
- Mix of confidence levels (high/medium/low)
- Output is blind for annotators (LLM picks hidden in a separate file)

Deliverables:
  annotations/v2_validation_sample.md           — blind annotation packet (annotators see this)
  annotations/v2_validation_picks_hidden.jsonl  — LLM v1+v2 picks (reveal after annotation)
  annotations/v2_validation_results.csv         — empty CSV for collecting annotator labels
"""
from __future__ import annotations
import json, random, re
from collections import Counter, defaultdict
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "failure_analysis/androidworld/cli"))
from verify_logs import read_trajectory  # noqa: E402

JUDGE_DIR = REPO / "failure_analysis/androidworld/cli/judge/outputs"
OUT_DIR = REPO / "failure_analysis/androidworld/cli/annotations"
OUT_DIR.mkdir(parents=True, exist_ok=True)

RAND_SEED = 42  # deterministic so the sample is reproducible

# Focused 15-trajectory validation collection (uploaded 2026-05-12 via ingest_15_validation.py)
DOCENT_COLLECTION_ID = "bb2d8166-2a47-4b8b-80d1-27dcd7603954"
DOCENT_FRONTEND = "https://docent.transluce.org"


def docent_run_url(agent_run_id: str) -> str:
    return f"{DOCENT_FRONTEND}/dashboard/{DOCENT_COLLECTION_ID}/agent_run/{agent_run_id}"


# Hard-coded mapping of trajectory_id → agent_run_id in the focused validation collection
# (pulled from Docent collection bb2d8166 on 2026-05-12).
TRAJECTORY_TO_RUN_ID = {
    "Terminus2_openaigpt53codex_seed30_bash_only__t083":            "7d6d0b08-ccbf-44e2-8daa-bb3d0c54448d",
    "ClaudeCodeCLI_claudesonnet46_seed30_bash_only__t079":          "1635544c-1dbd-4e56-8e8f-e38a7356177d",
    "ClaudeCodeCLI_claudeopus47_seed30_bash_only__t053":            "26c72bc6-e824-4429-a585-c52910b80a99",
    "Terminus2_openrouterminimaxminimaxm27_seed30_bash_only__t048": "891a5f07-cce5-4cbd-9153-fb1251d3cef6",
    "MiniSweAgent_openaigpt53codex_seed30_bash_only__t087":         "c2c3073f-f541-427d-84db-83517b68f34f",
    "Terminus2_openrouterminimaxminimaxm27_seed30_bash_only__t032": "2cd942df-8a31-48ee-9c22-d19bbabdd713",
    "Terminus2_openrouterminimaxminimaxm27_seed30_bash_only__t013": "ccd6f761-e3b7-46b7-8c57-7bd667c7dcc3",
    "MiniSweAgent_openaigpt53codex_seed30_bash_only__t006":         "d6c04cd6-8ae4-4dfa-9f32-2fad3dac7c2e",
    "Terminus2_openrouterminimaxminimaxm27_seed30_bash_only__t102": "eac0fcd9-905b-47aa-9c6b-ac3e82980ab5",
    "MiniSweAgent_openaigpt53codex_seed30_bash_only__t048":         "a1f2c223-5650-4371-af79-a1a68e788e71",
    "Terminus2_openrouterminimaxminimaxm27_seed30_bash_only__t073": "068cd368-69f9-4ed2-a1f4-5a633700aed6",
    "Terminus2_openaigpt53codex_seed30_bash_only__t056":            "dfde8650-d174-47fd-ada0-e9779b951c25",
    "ClaudeCodeCLI_claudeopus47_seed30_bash_only__t039":            "c831b017-7461-4e6d-a8ec-150994958262",
    "MiniSweAgent_openaigpt53codex_seed30_bash_only__t010":         "45af05c8-534f-41fb-b8df-5338259e124b",
    "ClaudeCodeCLI_claudeopus47_seed30_bash_only__t022":            "37df4e68-2138-4409-907f-38d9ae8c7bf0",
}


def filter_cli_solvable(rows):
    text = (REPO / "docs/final/AndroidWorld2026/androidworld_ground_truth_reference_v2.md").read_text()
    GUI = set(); cur = None
    for ln in text.splitlines():
        m = re.match(r"###\s+Task\s+0?(\d+):", ln)
        if m: cur = int(m.group(1))
        elif cur is not None and re.match(r"\*\*Status:\*\*\s*GUI-only", ln):
            GUI.add(cur); cur = None
        elif cur is not None and ln.startswith("**Status:**"):
            cur = None
    return [r for r in rows if r["task_id"] not in GUI]


def condense(traj_path):
    """Full trajectory for annotators — NO truncation. Every step, message, observation,
    system prompt, and submission rendered in full from the underlying ATIF / MiniSWE
    native file. The resulting packet may be large but annotators get the complete trace."""
    p = REPO / traj_path
    raw = json.loads(p.read_text())
    out = []
    if raw.get("schema_version", "").startswith("ATIF-"):
        for s in raw.get("steps", []):
            src = s.get("source"); msg = (s.get("message") or "")
            if src == "system":
                out.append(f"=== SYSTEM PROMPT ({len(msg)} chars) ===")
                out.append(msg)
                out.append("=== END SYSTEM PROMPT ===")
                continue
            if src == "user":
                out.append(f"=== USER TASK ===")
                out.append(msg)
                out.append("=== END USER TASK ===")
                continue
            # agent
            obs = s.get("observation")
            obs_str = ""
            if obs:
                obs_text = obs if isinstance(obs, str) else json.dumps(obs)
                m = re.search(r'"content":\s*"((?:[^"\\]|\\.)*)"', obs_text)
                if m:
                    obs_str = m.group(1).encode().decode('unicode_escape', errors='ignore')
                else:
                    obs_str = obs_text
            out.append(f"[step {s.get('step_id', 0)}] AGENT: {msg}")
            if obs_str:
                out.append(f"          OBS: {obs_str}")
    elif "messages" in raw:
        for i, m in enumerate(raw.get("messages", [])):
            role = m.get("role"); content = (m.get("content") or "")
            if role == "system":
                out.append(f"=== SYSTEM ({len(content)} chars) ===")
                out.append(content)
                out.append("=== END SYSTEM ===")
                continue
            if role == "user" and i == 1:
                out.append(f"=== USER TASK ===")
                out.append(content)
                out.append("=== END USER TASK ===")
                continue
            if role == "assistant":
                out.append(f"[msg {i}] AGENT: {content}")
            elif role == "user":
                out.append(f"          OBS: {content}")
        sub = (raw.get("info") or {}).get("submission")
        if sub:
            out.append(f"=== SUBMISSION ===")
            out.append(sub)
            out.append("=== END SUBMISSION ===")
    return "\n".join(out)


def main():
    # Load v1 and v2 results
    v1 = {r["trajectory_id"]: r for r in
          (json.loads(l) for l in (JUDGE_DIR/"judge_results.jsonl").read_text().splitlines() if l.strip())}
    v2 = {r["trajectory_id"]: r for r in
          (json.loads(l) for l in (JUDGE_DIR/"judge_results_v2.jsonl").read_text().splitlines() if l.strip())}

    # Load pilot for trajectory paths
    pilot = {r["trajectory_id"]: r for r in
             (json.loads(l) for l in (REPO/"failure_analysis/androidworld/cli/data/pilot_set.jsonl").read_text().splitlines() if l.strip())}

    # CLI-solvable filter
    shared_ids = [tid for tid in v1 if tid in v2 and tid in pilot]
    cli = [tid for tid in shared_ids if v2[tid]["task_id"] not in
           {0,1,8,20,28,29,30,37,40,47,55,75,76,78,80}]
    print(f"CLI-solvable: {len(cli)}")

    # Group by v2 primary leaf
    by_leaf = defaultdict(list)
    for tid in cli:
        by_leaf[v2[tid]["primary_leaf"]].append(tid)

    # Sampling targets per leaf (totaling 15)
    targets = {
        "disobey_specification": 5,
        "step_repetition": 2,
        "premature_termination": 2,
        "reasoning_action_mismatch": 2,
        "weak_verification": 1,
        "unaware_of_termination_conditions": 1,
        "no_or_incorrect_verification": 1,
        "_no_match_": 1,
    }

    rng = random.Random(RAND_SEED)
    sampled_ids = []
    for leaf, n in targets.items():
        pool = by_leaf.get(leaf, [])
        if not pool:
            continue
        k = min(n, len(pool))
        sampled_ids.extend(rng.sample(pool, k))

    # If we're short of 15, top up from disobey_spec (the biggest pool)
    while len(sampled_ids) < 15:
        spare = [t for t in by_leaf["disobey_specification"] if t not in sampled_ids]
        if not spare: break
        sampled_ids.append(rng.choice(spare))

    sampled_ids = sampled_ids[:15]
    print(f"Sampled {len(sampled_ids)} trajectories.")

    # ----------- Build the blind annotation packet -----------
    md = []
    md.append("# v2 Rubric Validation — Two-Annotator Hand-Label Packet")
    md.append("")
    md.append("**Pool:** 15 trajectories sampled from 211 CLI-solvable readable failures")
    md.append("**Rubric:** Use `failure_analysis/androidworld/cli/rubric/rubric_v2.md`")
    md.append("**Reproducibility:** seed=42")
    md.append("")
    md.append("## Annotator instructions")
    md.append("")
    md.append("For each of the 15 trajectories below:")
    md.append("1. Read the task description and the trajectory excerpt.")
    md.append("2. Read `rubric_v2.md` if you haven't already (especially the 9 leaf decision procedures).")
    md.append("3. **Independently** (annotators should NOT discuss before labeling):")
    md.append("   - Assign exactly one `primary_leaf` from the 9 v2 leaves (or `_no_match_`).")
    md.append("   - List zero or more `secondary_leaves` if other leaves also fire.")
    md.append("   - Write a 1-2 sentence rationale citing specific step numbers.")
    md.append("   - Record your `confidence` (low/medium/high).")
    md.append("4. Fill in the entry in `v2_validation_results.csv`.")
    md.append("")
    md.append("After both annotators complete: compute inter-annotator agreement (Cohen's κ on primary_leaf) and compare against the LLM judge picks revealed in `v2_validation_picks_hidden.jsonl`.")
    md.append("")
    md.append("## v2 leaf reference (one-line summaries)")
    md.append("")
    md.append("- **disobey_specification** — wrong consumer surface / wrong API level / wrong output format / fabricated data when source named / forbidden ops")
    md.append("- **step_repetition** — same ADB command class against same target ≥ 2× without strategy change")
    md.append("- **unaware_of_termination_conditions** — continued past Android success/futility signal (C1 or C2)")
    md.append("- **context_loss** — forgot established device state or task content within a recent window")
    md.append("- **task_derailment** — sub-goal drifted from primary objective for ≥ 2 turns")
    md.append("- **reasoning_action_mismatch** — reasoning vs action: declared method ≠ actual, uncertainty-then-commit, intent vs encoded-command")
    md.append("- **premature_termination** — finish before objectives met; positive PT (claimed success) or negative PT (gave up empty)")
    md.append("- **no_or_incorrect_verification** — completed without any substantive read against authoritative surface")
    md.append("- **weak_verification** — verified, but via wrong surface (same-surface read after write; provider-notification gap)")
    md.append("- **_no_match_** — none of the above (rare; explain)")
    md.append("")
    md.append("---")
    md.append("")

    hidden_picks = []

    for i, tid in enumerate(sampled_ids, 1):
        v1r = v1[tid]
        v2r = v2[tid]
        pilot_r = pilot[tid]
        traj_path = pilot_r["traj_path"]
        traj_text = condense(traj_path)

        run_id = TRAJECTORY_TO_RUN_ID.get(tid, "UNKNOWN")
        docent_url = docent_run_url(run_id) if run_id != "UNKNOWN" else "N/A"
        md.append(f"## Trajectory {i:>2d} — task {v2r['task_id']} ({v2r['agent_class']})")
        md.append("")
        md.append(f"**🔗 Open in Docent UI:** {docent_url}")
        md.append("")
        md.append(f"**Trajectory ID:** `{tid}`")
        md.append(f"**Agent class:** {v2r['agent_class']}")
        md.append(f"**Task ID:** {v2r['task_id']}")
        md.append(f"**Step count:** {pilot_r.get('step_count')}/{pilot_r.get('max_turns')}")
        md.append("")
        md.append(f"**Task description:**")
        md.append("```")
        md.append((v2r.get("task_name") or "")[:400])
        md.append("```")
        md.append("")
        md.append(f"**Full trajectory ({pilot_r.get('step_count')} agent steps):**")
        md.append("```")
        md.append(traj_text)
        md.append("```")
        md.append("")
        md.append("### Your annotation")
        md.append("")
        md.append("**Annotator A:**")
        md.append("- primary_leaf: ___________________")
        md.append("- secondary_leaves: [___________________]")
        md.append("- confidence: ___________________")
        md.append("- rationale: ___________________")
        md.append("")
        md.append("**Annotator B:**")
        md.append("- primary_leaf: ___________________")
        md.append("- secondary_leaves: [___________________]")
        md.append("- confidence: ___________________")
        md.append("- rationale: ___________________")
        md.append("")
        md.append("---")
        md.append("")

        hidden_picks.append({
            "trajectory_id": tid,
            "task_id": v2r["task_id"],
            "agent_class": v2r["agent_class"],
            "task_name": v2r.get("task_name"),
            "v2_primary": v2r["primary_leaf"],
            "v2_secondary": v2r.get("secondary_leaves", []),
            "v2_confidence": v2r.get("confidence"),
            "v2_rationale": v2r.get("rationale"),
        })

    md_path = OUT_DIR / "v2_validation_sample.md"
    md_path.write_text("\n".join(md))
    print(f"Wrote: {md_path.relative_to(REPO)}  ({md_path.stat().st_size//1024} KB)")

    # Slim variant: Docent-first packet (just metadata + Docent URLs, no trajectory body)
    slim = []
    slim.append("# v2 Rubric Validation — Two-Annotator Packet (Docent-first)")
    slim.append("")
    slim.append("**Pool:** 15 trajectories sampled from 211 CLI-solvable readable failures.")
    slim.append(f"**Docent collection:** {DOCENT_FRONTEND}/dashboard/{DOCENT_COLLECTION_ID}")
    slim.append("")
    slim.append("**Read each trajectory in the Docent UI** using the links below. The UI renders each agent step + observation natively, supports navigation, and shows the LLM judge's existing readings (v1 and v2) — but please **do not consult those before forming your independent annotation**.")
    slim.append("")
    slim.append("After reading, fill in your annotation in `v2_validation_results.csv` (one row per trajectory, two columns per annotator).")
    slim.append("")
    slim.append("## v2 leaf reference (one-line summaries)")
    slim.append("")
    slim.append("- **disobey_specification** — wrong consumer surface / wrong API level / wrong output format / fabricated data when source named / forbidden ops")
    slim.append("- **step_repetition** — same ADB command class against same target ≥ 2× without strategy change")
    slim.append("- **unaware_of_termination_conditions** — continued past Android success/futility signal (C1 or C2)")
    slim.append("- **context_loss** — forgot established device state or task content within a recent window")
    slim.append("- **task_derailment** — sub-goal drifted from primary objective for ≥ 2 turns")
    slim.append("- **reasoning_action_mismatch** — reasoning vs action: declared method ≠ actual, uncertainty-then-commit, intent vs encoded-command")
    slim.append("- **premature_termination** — finish before objectives met; positive PT (claimed success) or negative PT (gave up empty)")
    slim.append("- **no_or_incorrect_verification** — completed without any substantive read against authoritative surface")
    slim.append("- **weak_verification** — verified, but via wrong surface (same-surface read after write; provider-notification gap)")
    slim.append("- **_no_match_** — none of the above (rare; explain)")
    slim.append("")
    slim.append("Read the full v2 rubric at `failure_analysis/androidworld/cli/rubric/rubric_v2.md` before starting.")
    slim.append("")
    slim.append("## The 15 trajectories")
    slim.append("")
    slim.append("| # | Task | Agent | Steps | Docent link |")
    slim.append("|---:|---:|---|---:|---|")
    for i, h in enumerate(hidden_picks, 1):
        tid = h["trajectory_id"]
        run_id = TRAJECTORY_TO_RUN_ID.get(tid, "UNKNOWN")
        url = docent_run_url(run_id) if run_id != "UNKNOWN" else "N/A"
        agent_short = h["agent_class"]
        pilot_r = pilot[tid]
        steps_str = f"{pilot_r.get('step_count')}/{pilot_r.get('max_turns')}"
        # Brief task description, truncated
        task = (h.get("task_name") or "").replace("\n", " ")[:60]
        slim.append(f"| {i} | {h['task_id']} | {agent_short} | {steps_str} | [Open]({url}) — {task} |")
    slim.append("")
    slim.append("## Annotation template (one entry per trajectory)")
    slim.append("")
    slim.append("Fill in the CSV `v2_validation_results.csv`. Each annotator gets a separate column set.")
    slim.append("Required fields per annotator:")
    slim.append("- `primary_leaf` (one of the 9 v2 leaves or `_no_match_`)")
    slim.append("- `secondary_leaves` (comma-separated list, possibly empty)")
    slim.append("- `confidence` (low/medium/high)")
    slim.append("- `rationale` (1-2 sentences citing specific step numbers)")
    slim.append("")
    slim.append("## Collaborative annotation in Docent UI")
    slim.append("")
    slim.append("Docent supports two collaborative features per agent run:")
    slim.append("")
    slim.append("1. **Comments** — every agent run page has a comment thread at the bottom of the right panel. Teammates can leave discussion notes (\"why did the agent do X?\", \"this looks like RAM not DS\") that are visible to everyone with collection access.")
    slim.append("2. **Labels** — teammates with collection access can apply structured labels to each agent run. For this validation, apply a label corresponding to your chosen v2 primary leaf (e.g., `v2/disobey_specification`).")
    slim.append("")
    slim.append("**Teammate access:** add your collaborators to the Docent organization at https://docent.transluce.org/settings/team, then grant access to this collection. They will be able to view, comment on, and label the agent runs.")
    slim.append("")
    slim.append("## After both annotators finish")
    slim.append("")
    slim.append("Reveal `v2_validation_picks_hidden.jsonl` to see the v2 LLM judge's picks and rationales. Compute:")
    slim.append("- Cohen's κ on `primary_leaf` (A vs B) — inter-annotator agreement (target ≥ 0.6)")
    slim.append("- Cohen's κ on `primary_leaf` (each annotator vs v2 LLM judge) — target ≥ 0.6")

    slim_path = OUT_DIR / "v2_validation_sample_docent.md"
    slim_path.write_text("\n".join(slim))
    print(f"Wrote: {slim_path.relative_to(REPO)}  ({slim_path.stat().st_size//1024} KB) — Docent-first packet")

    hidden_path = OUT_DIR / "v2_validation_picks_hidden.jsonl"
    hidden_path.write_text("\n".join(json.dumps(r) for r in hidden_picks) + "\n")
    print(f"Wrote: {hidden_path.relative_to(REPO)}")

    # CSV for collecting annotator picks
    csv_lines = ["trajectory_id,task_id,agent_class,A_primary,A_secondary,A_confidence,A_rationale,B_primary,B_secondary,B_confidence,B_rationale"]
    for r in hidden_picks:
        csv_lines.append(f'{r["trajectory_id"]},{r["task_id"]},{r["agent_class"]},,,,,,,,')
    csv_path = OUT_DIR / "v2_validation_results.csv"
    csv_path.write_text("\n".join(csv_lines) + "\n")
    print(f"Wrote: {csv_path.relative_to(REPO)}")

    # Sampling diagnostic
    print()
    print("Sample composition:")
    print(f"  By v2 primary leaf: {Counter(v2[t]['primary_leaf'] for t in sampled_ids).most_common()}")
    print(f"  By agent: {Counter(v2[t]['agent_class'] for t in sampled_ids).most_common()}")
    print(f"  v1↔v2 disagreement: {sum(1 for t in sampled_ids if v1[t]['primary_leaf'] != v2[t]['primary_leaf'])}/15")
    print(f"  Confidence (v2): {Counter(v2[t]['confidence'] for t in sampled_ids).most_common()}")


if __name__ == "__main__":
    main()
