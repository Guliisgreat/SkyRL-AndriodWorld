#!/usr/bin/env python3
"""Figure 4 — TB-paper-style grouped bar chart: failure-mode *prevalence*
across the 9 TB leaves, CLI vs GUI.

Layout matches the Terminal-Bench paper (Bonatti et al., Fig. of Appendix C):
- 2 groups on x-axis: CLI, GUI
- 9 bars per group (one per TB leaf), ordered: Execution (blue), Coherence (red),
  Verification (orange); within each color, solid → hatch1 → hatch2 distinguishes
  the 3 leaves.

Y-axis is **prevalence**: % of trajectories whose primary OR any secondary cluster
maps to that TB leaf (a trajectory can contribute to multiple bars). This is the
TB-paper convention and is *different* from share-of-primary (used in Fig. 3).

Fair view only: both pools are restricted to the 103 CLI-solvable AndroidWorld
tasks (13 GUI-only tasks excluded).
"""
from __future__ import annotations
import csv
import json
import re
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from _render_lib import (
    GUI_ONLY_TASK_IDS, task_id_from_trajectory_id,
    load_cluster_to_leaf, load_labels, normalize_leaf,
)

ROOT = Path(__file__).resolve().parent
WS_CLI = ROOT.parent / "2026-05-21_android-cli-failures-combined"
WS_GUI = ROOT.parent / "2026-05-22_android-gui-failures"
CLI_LABELS = WS_CLI / "classification/cluster_labels_full.jsonl"
CLI_MAP    = WS_CLI / "consensus_mapping_v3.json"
GUI_LABELS = WS_GUI / "classification/cluster_labels.jsonl"
GUI_MAP    = WS_GUI / "consensus_mapping_gui.json"


# TB-paper bar order within each color group:
LEAF_PLOT_ORDER = [
    # Execution (blue family)
    "Disobey Specification",
    "Step Repetition",
    "Unaware of Termination",
    # Coherence (red family)
    "Reasoning-Action Mismatch",
    "Context Loss",
    "Task Derailment",
    # Verification (orange family)
    "Premature Termination",
    "No or Incorrect Verification",
    "Weak Verification",
]

LEAF_GROUP = {
    "Disobey Specification":        "Execution",
    "Step Repetition":              "Execution",
    "Unaware of Termination":       "Execution",
    "Reasoning-Action Mismatch":    "Coherence",
    "Context Loss":                 "Coherence",
    "Task Derailment":              "Coherence",
    "Premature Termination":        "Verification",
    "No or Incorrect Verification": "Verification",
    "Weak Verification":            "Verification",
}

# Match TB-paper palette
GROUP_COLOR = {
    "Execution":    "#3D7CC8",  # blue
    "Coherence":    "#D6322C",  # red
    "Verification": "#F5A623",  # orange
}

# Within each color group, distinguish the 3 leaves by hatch
LEAF_HATCH = {
    # Execution
    "Disobey Specification":        "",
    "Step Repetition":              "////",
    "Unaware of Termination":       r"\\\\",
    # Coherence
    "Reasoning-Action Mismatch":    "",
    "Context Loss":                 "////",
    "Task Derailment":              r"\\\\",
    # Verification
    "Premature Termination":        "",
    "No or Incorrect Verification": "////",
    "Weak Verification":            r"\\\\",
}


def compute_prevalence(labels_path: Path, cluster_to_leaf: dict) -> tuple[int, dict[str, float]]:
    """For each trajectory in the fair-view subset, collect the *set* of TB
    leaves it touches (primary leaf + leaves of any secondary clusters).
    Returns (n_trajectories, {leaf: prevalence_pct}).
    """
    n = 0
    leaf_trajs: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    for r in load_labels(labels_path):
        tid = task_id_from_trajectory_id(r.get("trajectory_id", ""))
        if tid is None or tid in GUI_ONLY_TASK_IDS:
            continue
        clusters = [r["primary_cluster"]] + list(r.get("secondary_clusters") or [])
        leaves = set()
        for c in clusters:
            if c in cluster_to_leaf:
                leaves.add(normalize_leaf(cluster_to_leaf[c]))
            else:
                missing[c] += 1
        n += 1
        for l in leaves:
            leaf_trajs[l] += 1
    if missing:
        print(f"  WARN — {len(missing)} secondary clusters not in consensus "
              f"mapping ({sum(missing.values())} refs): {dict(missing)}")
    prev = {l: leaf_trajs[l] / n * 100 for l in LEAF_PLOT_ORDER}
    return n, prev


def render(cli_n: int, cli_prev: dict, gui_n: int, gui_prev: dict,
           out_pdf: Path, out_png: Path, title: str | None = None) -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.labelcolor": "#222",
        "xtick.color": "#222",
        "ytick.color": "#222",
        "axes.edgecolor": "#444",
    })
    fig, ax = plt.subplots(figsize=(11, 5.5))

    # Drop TB leaves that are 0% in BOTH paradigms; keep TB-paper bar order
    active_leaves = [
        l for l in LEAF_PLOT_ORDER
        if cli_prev.get(l, 0) > 0 or gui_prev.get(l, 0) > 0
    ]
    absent_leaves = [l for l in LEAF_PLOT_ORDER if l not in active_leaves]

    n_leaves = len(active_leaves)
    bar_width = 0.075         # narrower bars
    intra_gap = 0.015         # tiny gap between bars within a group
    pitch = bar_width + intra_gap
    group_span = n_leaves * pitch - intra_gap
    group_gap = group_span * 1.4   # large breathing room between paradigms

    group_starts = [0.0, group_span + group_gap]
    paradigm_labels = ["CLI", "GUI"]
    paradigm_data = [(cli_n, cli_prev), (gui_n, gui_prev)]

    bar_positions: list[list[float]] = []
    for start in group_starts:
        positions = [start + i * pitch for i in range(n_leaves)]
        bar_positions.append(positions)

    for grp_idx, (_, prev) in enumerate(paradigm_data):
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
        for i in range(2)
    ]
    ax.set_xticks(group_label_x)
    ax.set_xticklabels(paradigm_labels, fontsize=13, fontweight="bold")
    ax.tick_params(axis="x", which="both", length=0, pad=8)
    # Generous horizontal padding so the groups feel anchored, not squashed
    side_pad = group_span * 0.6
    ax.set_xlim(bar_positions[0][0] - side_pad,
                bar_positions[1][-1] + bar_width + side_pad)

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


    # Legend — only leaves that appear in the plot, grouped by Exec/Coh/Ver.
    # Append a final block listing absent (0% in both) leaves in italics.
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

    if title:
        ax.set_title(title, fontsize=13, fontweight="bold",
                     color="#222", pad=14)

    fig.tight_layout()
    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=200, bbox_inches="tight")
    print(f"saved → {out_pdf.name}, {out_png.name}")
    print(f"  active leaves ({len(active_leaves)}): {active_leaves}")
    print(f"  absent leaves ({len(absent_leaves)}): {absent_leaves}")


def main():
    cli_c2l = load_cluster_to_leaf(CLI_MAP)
    gui_c2l = load_cluster_to_leaf(GUI_MAP)

    print("CLI prevalence:")
    cli_n, cli_prev = compute_prevalence(CLI_LABELS, cli_c2l)
    print(f"  fair-view n = {cli_n}")
    for leaf in LEAF_PLOT_ORDER:
        print(f"    {leaf:35s} {cli_prev[leaf]:5.1f}%")

    print("\nGUI prevalence:")
    gui_n, gui_prev = compute_prevalence(GUI_LABELS, gui_c2l)
    print(f"  fair-view n = {gui_n}")
    for leaf in LEAF_PLOT_ORDER:
        print(f"    {leaf:35s} {gui_prev[leaf]:5.1f}%")

    render(cli_n, cli_prev, gui_n, gui_prev,
           ROOT / "figure4_paradigm_tb_grouped.pdf",
           ROOT / "figure4_paradigm_tb_grouped.png")

    with (ROOT / "figure4_data.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["paradigm", "n_failures", "tb_leaf", "group", "prevalence_pct"])
        for label, n, prev in [("CLI", cli_n, cli_prev), ("GUI", gui_n, gui_prev)]:
            for leaf in LEAF_PLOT_ORDER:
                w.writerow([label, n, leaf, LEAF_GROUP[leaf],
                            f"{prev[leaf]:.2f}"])
    print(f"wrote → figure4_data.csv")


if __name__ == "__main__":
    main()
