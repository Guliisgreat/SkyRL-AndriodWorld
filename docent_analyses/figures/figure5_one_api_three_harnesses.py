#!/usr/bin/env python3
"""Figure 5 — TB-paper-style grouped bar chart: failure-mode prevalence
across the 9 TB leaves, holding the model fixed and varying the CLI harness.

All three diagrams share the same 3-harness x-axis (ClaudeCodeCLI, MiniSweAgent,
Terminus2) for visual consistency. A harness that didn't run a given model
shows an italic "no runs" caption in its slot.

Same visual conventions as figure4_paradigm_tb_grouped.py:
  - Y-axis: prevalence (% of trajectories where a primary OR secondary
    cluster maps to that TB leaf — bars need not sum to 100%)
  - Color groups: Execution=blue, Coherence=red, Verification=orange
  - Within color: solid + 2 hatch patterns to distinguish 3 leaves
  - Active leaves = nonzero in at least one harness in this model's figure

Fair view only: 13 GUI-only AndroidWorld tasks excluded.

Outputs:
  figure5_sonnet46_three_harnesses.{pdf,png}    — Claude Sonnet 4.6
  figure5_codex_three_harnesses.{pdf,png}       — GPT-5.3 Codex (no ClaudeCodeCLI runs)
  figure5_minimax_three_harnesses.{pdf,png}     — MiniMax M2.7   (no ClaudeCodeCLI runs)
  figure5_data.csv                              — long-format data for all three
"""
from __future__ import annotations
import csv
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from _render_lib import (
    GUI_ONLY_TASK_IDS, task_id_from_trajectory_id,
    load_cluster_to_leaf, load_labels, normalize_leaf,
)
from figure4_paradigm_tb_grouped import (
    LEAF_PLOT_ORDER, LEAF_GROUP, GROUP_COLOR, LEAF_HATCH,
)

ROOT = Path(__file__).resolve().parent
WS_CLI = ROOT.parent / "2026-05-21_android-cli-failures-combined"
CLI_LABELS = WS_CLI / "classification/cluster_labels_full.jsonl"
CLI_MAP    = WS_CLI / "consensus_mapping_v3.json"

# All three diagrams share the same 3-harness x-axis. ClaudeCodeCLI never ran
# Codex or MiniMax (it is a Claude-only harness), so those slots render empty.
SHARED_HARNESS_ORDER = ["ClaudeCodeCLI", "MiniSweAgent", "Terminus2"]

# (model_label, accepted model_api strings, output basename)
MODEL_VARIANTS = [
    ("claude-sonnet-4.6",
     {"claudesonnet46", "anthropicclaudesonnet46"},
     "figure5_sonnet46_three_harnesses"),
    ("gpt-5.3-codex",
     {"openaigpt53codex"},
     "figure5_codex_three_harnesses"),
    ("minimax-m2.7",
     {"openrouterminimaxminimaxm27"},
     "figure5_minimax_three_harnesses"),
]


def compute_prevalence_for_harness(rows: list[dict], harness: str,
                                   accepted_apis: set[str],
                                   cluster_to_leaf: dict
                                   ) -> tuple[int, dict[str, float]]:
    n = 0
    leaf_trajs: Counter[str] = Counter()
    for r in rows:
        if r.get("agent_harness") != harness:
            continue
        if r.get("model_api") not in accepted_apis:
            continue
        tid = task_id_from_trajectory_id(r.get("trajectory_id", ""))
        if tid is None or tid in GUI_ONLY_TASK_IDS:
            continue
        clusters = [r["primary_cluster"]] + list(r.get("secondary_clusters") or [])
        leaves = {normalize_leaf(cluster_to_leaf[c])
                  for c in clusters if c in cluster_to_leaf}
        n += 1
        for l in leaves:
            leaf_trajs[l] += 1
    prev = {l: (leaf_trajs[l] / n * 100 if n else 0.0) for l in LEAF_PLOT_ORDER}
    return n, prev


def render(harness_data: list[tuple[str, int, dict]],
           out_pdf: Path, out_png: Path) -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.labelcolor": "#222",
        "xtick.color": "#222",
        "ytick.color": "#222",
        "axes.edgecolor": "#444",
    })
    fig, ax = plt.subplots(figsize=(13, 5.5))

    # Active leaves = any leaf with >0% in at least one harness for THIS model
    active_leaves = [
        l for l in LEAF_PLOT_ORDER
        if any(prev.get(l, 0) > 0 for _, _, prev in harness_data)
    ]
    if not active_leaves:
        active_leaves = LEAF_PLOT_ORDER[:1]  # at least one slot for layout

    n_leaves = len(active_leaves)
    bar_width = 0.075
    intra_gap = 0.015
    pitch = bar_width + intra_gap
    group_span = n_leaves * pitch - intra_gap
    group_gap = group_span * 1.4

    n_groups = len(harness_data)
    group_starts = [i * (group_span + group_gap) for i in range(n_groups)]

    bar_positions: list[list[float]] = []
    for start in group_starts:
        positions = [start + i * pitch for i in range(n_leaves)]
        bar_positions.append(positions)

    for grp_idx, (_, n_traj, prev) in enumerate(harness_data):
        if n_traj == 0:
            # Empty harness slot — annotate "no runs" at mid-height
            mid_x = (bar_positions[grp_idx][0]
                     + bar_positions[grp_idx][-1]) / 2
            ax.text(mid_x, 50, "no runs", ha="center", va="center",
                    fontsize=11, color="#888", style="italic")
            continue
        for li, leaf in enumerate(active_leaves):
            group = LEAF_GROUP[leaf]
            color = GROUP_COLOR[group]
            hatch = LEAF_HATCH[leaf]
            x = bar_positions[grp_idx][li]
            h = prev[leaf]
            ax.bar(x, h, width=bar_width,
                   color=color, edgecolor="#222", linewidth=0.7,
                   hatch=hatch, zorder=3)
            if h >= 1.0:
                ax.text(x, h + 1.8, f"{h:.0f}%", ha="center", va="bottom",
                        fontsize=9, color="#333", zorder=4)

    group_label_x = [
        (bar_positions[i][0] + bar_positions[i][-1]) / 2
        for i in range(n_groups)
    ]
    ax.set_xticks(group_label_x)
    ax.set_xticklabels([h for h, _, _ in harness_data],
                       fontsize=13, fontweight="bold")
    ax.tick_params(axis="x", which="both", length=0, pad=8)

    side_pad = group_span * 0.6
    ax.set_xlim(bar_positions[0][0] - side_pad,
                bar_positions[-1][-1] + bar_width + side_pad)

    ax.set_ylabel("Failure prevalence (%)", fontsize=12)
    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 20))
    ax.tick_params(axis="y", which="both", length=0, labelsize=10)
    ax.grid(axis="y", alpha=0.35, linestyle=(0, (4, 4)), linewidth=0.7,
            color="#999", zorder=1)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color("#444")
    ax.spines["bottom"].set_linewidth(0.8)

    # Legend grouped by Execution / Coherence / Verification — only active leaves
    legend_handles = []
    last_group = None
    for leaf in active_leaves:
        group = LEAF_GROUP[leaf]
        if group != last_group:
            legend_handles.append(mpatches.Patch(
                color="none", label=f"$\\bf{{{group}}}$"))
            last_group = group
        legend_handles.append(mpatches.Patch(
            facecolor=GROUP_COLOR[group], edgecolor="#222",
            linewidth=0.7, hatch=LEAF_HATCH[leaf],
            label=f"  {leaf}"))

    leg = ax.legend(handles=legend_handles, loc="center left",
                    bbox_to_anchor=(1.015, 0.5), fontsize=10,
                    frameon=True, handlelength=2.2, handleheight=1.4,
                    borderpad=0.9, labelspacing=0.55)
    leg.get_frame().set_edgecolor("#bbb")
    leg.get_frame().set_linewidth(0.8)
    leg.get_frame().set_facecolor("#fafafa")

    fig.tight_layout()
    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=200, bbox_inches="tight")
    print(f"saved → {out_pdf.name}, {out_png.name}")
    print(f"  active leaves ({len(active_leaves)}): {active_leaves}")


def main():
    c2l = load_cluster_to_leaf(CLI_MAP)
    rows = load_labels(CLI_LABELS)

    csv_path = ROOT / "figure5_data.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "harness", "n_failures", "tb_leaf", "group",
                    "prevalence_pct"])

        for model_label, accepted_apis, basename in MODEL_VARIANTS:
            print(f"\n========== {model_label} ==========")
            harness_data = []
            for h in SHARED_HARNESS_ORDER:
                n, prev = compute_prevalence_for_harness(rows, h, accepted_apis, c2l)
                harness_data.append((h, n, prev))
                print(f"  {h}: n_fair = {n}")

            render(harness_data,
                   ROOT / f"{basename}.pdf",
                   ROOT / f"{basename}.png")

            for h, n, prev in harness_data:
                for leaf in LEAF_PLOT_ORDER:
                    w.writerow([model_label, h, n, leaf,
                                LEAF_GROUP[leaf], f"{prev[leaf]:.2f}"])
    print(f"\nwrote → {csv_path.name}")


if __name__ == "__main__":
    main()
