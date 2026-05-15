"""Multi-label view of the rubric_flags.jsonl data.

Drops the single-label "primary_leaf" forcing. Each trajectory is annotated
with the SET of leaves whose detectors fire. Outputs:

  data/multilabel_flags.jsonl    one row per trajectory with leaves_set
  data/multilabel_summary.md     per-agent + global multi-label distribution

Usage:
    python multilabel_view.py            # generate both outputs
    python multilabel_view.py drilldown <agent>  # per-task multi-label drilldown
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DATA_DIR = REPO / "failure_analysis/androidworld/cli/data"

LEAF_KEYS = [
    "disobey_specification",
    "step_repetition",
    "unaware_of_termination_conditions",
    "context_loss",
    "task_derailment",
    "reasoning_action_mismatch",
    "premature_termination",
    "no_or_incorrect_verification",
    "weak_verification",
]


def load_rows() -> list[dict]:
    rows = [
        json.loads(l)
        for l in (DATA_DIR / "rubric_flags.jsonl").read_text().splitlines()
        if l.strip()
    ]
    pilot = {
        r["trajectory_id"]: r
        for r in (json.loads(l) for l in (DATA_DIR / "pilot_set.jsonl").read_text().splitlines() if l.strip())
    }
    out = []
    for r in rows:
        leaves = sorted(k for k in LEAF_KEYS if r["leaves"].get(k))
        out.append({
            **r,
            "matched_leaves": leaves,
            "n_leaves": len(leaves),
            "traj_path": pilot[r["trajectory_id"]]["traj_path"],
        })
    return out


def build_summary(rows: list[dict]) -> str:
    n = len(rows)
    md = []
    md.append("# Multi-Label Rubric Heuristic View — All 126 Failures")
    md.append("")
    md.append("> Each trajectory is annotated with the **set of all rubric leaves** whose")
    md.append("> heuristic detectors fire (multi-label). Drops the single-label priority")
    md.append("> assignment used in `rubric_summary.md`.")
    md.append("")
    md.append(f"**Pool:** {n} failures from `pilot_set.jsonl`")
    md.append("")

    # 1. Distribution of #leaves matched per trajectory
    n_leaves_dist = Counter(r["n_leaves"] for r in rows)
    md.append("## How many leaves fire per trajectory?")
    md.append("")
    md.append("| # Leaves matched | Count | % |")
    md.append("|---:|---:|---:|")
    for k in sorted(n_leaves_dist):
        c = n_leaves_dist[k]
        md.append(f"| {k} | {c} | {100*c/n:.0f}% |")
    md.append("")

    # 2. Per-leaf prevalence
    md.append("## Per-leaf prevalence (multi-label)")
    md.append("")
    md.append("Each row independent: how often does that leaf fire? Sums >100% because")
    md.append("a single trajectory can match multiple leaves.")
    md.append("")
    md.append("| TB leaf | Trajectories matched | % |")
    md.append("|---|---:|---:|")
    leaf_counts = Counter()
    for r in rows:
        for l in r["matched_leaves"]:
            leaf_counts[l] += 1
    for l in LEAF_KEYS:
        c = leaf_counts.get(l, 0)
        md.append(f"| {l.replace('_', ' ').strip()} | {c} | {100*c/n:.0f}% |")
    md.append("")

    # 3. Per-agent per-leaf
    by_agent = defaultdict(list)
    for r in rows:
        by_agent[r["agent_class"]].append(r)
    md.append("## Per-agent multi-label leaf prevalence")
    md.append("")
    md.append("Cell = % of that agent's failures where the leaf fires (independent).")
    md.append("")
    md.append("| Agent | n | " + " | ".join(l.replace("_", " ").strip() for l in LEAF_KEYS) + " |")
    md.append("|---|---:|" + "|".join(["---:"] * len(LEAF_KEYS)) + "|")
    for agent, items in by_agent.items():
        m = len(items)
        cells = []
        for l in LEAF_KEYS:
            c = sum(1 for r in items if l in r["matched_leaves"])
            cells.append(f"{100*c/m:.0f}%")
        md.append(f"| {agent} | {m} | " + " | ".join(cells) + " |")
    md.append("")

    # 4. Co-occurrence pairs
    md.append("## Top co-occurrence pairs")
    md.append("")
    md.append("Of trajectories matching ≥ 2 leaves, which leaf pairs appear together most?")
    md.append("")
    pair_counts = Counter()
    for r in rows:
        ll = r["matched_leaves"]
        for i in range(len(ll)):
            for j in range(i + 1, len(ll)):
                pair_counts[(ll[i], ll[j])] += 1
    md.append("| Leaf A | Leaf B | Count |")
    md.append("|---|---|---:|")
    for (a, b), c in pair_counts.most_common(15):
        md.append(f"| {a.replace('_', ' ')} | {b.replace('_', ' ')} | {c} |")
    md.append("")

    # 5. Trajectories with 0 leaves matched (heuristic blind spots)
    n_blind = sum(1 for r in rows if r["n_leaves"] == 0)
    md.append("## Heuristic blind-spots")
    md.append("")
    md.append(f"- **{n_blind} / {n} trajectories ({100*n_blind/n:.0f}%) match no leaf at all.**")
    md.append("  These are heuristic-blind: they failed for reasons no current detector catches.")
    md.append("  Per-agent:")
    for agent, items in by_agent.items():
        b = sum(1 for r in items if r["n_leaves"] == 0)
        md.append(f"  - {agent}: {b}/{len(items)} ({100*b/len(items):.0f}%) heuristic-blind")
    md.append("")
    md.append("These need the LLM judge to be classified.")

    return "\n".join(md)


def emit_jsonl(rows: list[dict]) -> None:
    out_path = DATA_DIR / "multilabel_flags.jsonl"
    with out_path.open("w") as f:
        for r in rows:
            f.write(json.dumps({
                "trajectory_id": r["trajectory_id"],
                "config": r["config"],
                "agent_class": r["agent_class"],
                "task_id": r["task_id"],
                "task_name": r["task_name"],
                "step_count": r["step_count"],
                "max_turns": r["max_turns"],
                "matched_leaves": r["matched_leaves"],
                "n_leaves": r["n_leaves"],
                "primary_detail": r["primary_detail"],
                "ambig1_step_rep_vs_ram": r.get("ambig1_step_rep_vs_ram"),
                "ambig2_disobey_vs_weak_verification": r.get("ambig2_disobey_vs_weak_verification"),
                "gap_honest_infeasibility": r.get("gap_honest_infeasibility"),
            }) + "\n")
    print(f"wrote {out_path.relative_to(REPO)}")


def drilldown(agent: str) -> None:
    rows = [r for r in load_rows() if r["agent_class"] == agent]
    rows.sort(key=lambda r: (-r["n_leaves"], r["task_id"]))
    print(f"# {agent} — multi-label per-trajectory drilldown ({len(rows)} failures)")
    print()
    print("Sorted by # leaves matched (descending) then task_id.")
    print()
    print("| # | task_id | step/max | n_leaves | matched leaves | task |")
    print("|---:|---:|---:|---:|---|---|")
    for i, r in enumerate(rows, 1):
        leaves = ", ".join(r["matched_leaves"]) if r["matched_leaves"] else "(blind)"
        task = r["task_name"][:80].replace("|", "\\|")
        print(f"| {i} | {r['task_id']} | {r['step_count']}/{r['max_turns']} | {r['n_leaves']} | {leaves} | {task} |")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "drilldown":
        agent = sys.argv[2] if len(sys.argv) > 2 else "ClaudeCodeCLI"
        drilldown(agent)
        return
    rows = load_rows()
    emit_jsonl(rows)
    md = build_summary(rows)
    out_path = DATA_DIR / "multilabel_summary.md"
    out_path.write_text(md)
    print(f"wrote {out_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
