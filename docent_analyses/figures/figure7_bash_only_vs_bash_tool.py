#!/usr/bin/env python3
"""Figure 7 — bash_only vs bash_tool variant comparison (CLI paradigm).

Same TB-paper visual conventions as figure 4 (CLI vs GUI):
  - 2 paradigm-like groups: bash_only · bash_tool (the agent's action-emit
    contract — naked shell strings vs structured tool-call JSON unwrapped by
    the harness)
  - Within each group: 5 bars for the active TB leaves
  - Color: blue = Execution, red = Coherence, orange = Verification
  - Hatch distinguishes leaves within a color band

Fair view only (CLI paradigm; 13 GUI-only AndroidWorld tasks excluded).
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

VARIANTS = ["bash_only", "bash_tool"]
VARIANT_DISPLAY = {"bash_only": "bash_only", "bash_tool": "bash_tool (+ tool wrapper)"}

# (model_label, accepted_apis_or_None, output_basename)
# accepted_apis = None means "all models pooled"
RUNS = [
    ("all models pooled", None, "figure7_bash_only_vs_bash_tool"),
    ("GPT-5.3 Codex",     {"openaigpt53codex"}, "figure7_codex_bash_only_vs_bash_tool"),
]


def compute_prevalence_for_variant(rows: list[dict], variant: str,
                                   cluster_to_leaf: dict,
                                   accepted_apis: set[str] | None = None,
                                   ) -> tuple[int, dict[str, float]]:
    n = 0
    leaf_trajs: Counter[str] = Counter()
    for r in rows:
        if r.get("action_variant") != variant:
            continue
        if accepted_apis is not None and r.get("model_api") not in accepted_apis:
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


def render(variant_data: list[tuple[str, int, dict]], out_pdf: Path,
           out_png: Path, title: str | None = None) -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.labelcolor": "#222",
        "xtick.color": "#222",
        "ytick.color": "#222",
        "axes.edgecolor": "#444",
    })
    fig, ax = plt.subplots(figsize=(11, 5.5))

    active_leaves = [
        l for l in LEAF_PLOT_ORDER
        if any(prev.get(l, 0) > 0 for _, _, prev in variant_data)
    ]
    n_leaves = len(active_leaves)
    bar_width = 0.075
    intra_gap = 0.015
    pitch = bar_width + intra_gap
    group_span = n_leaves * pitch - intra_gap
    group_gap = group_span * 1.4

    n_groups = len(variant_data)
    group_starts = [i * (group_span + group_gap) for i in range(n_groups)]
    bar_positions = [[s + i * pitch for i in range(n_leaves)] for s in group_starts]

    for grp_idx, (_, _, prev) in enumerate(variant_data):
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
    ax.set_xticklabels([VARIANT_DISPLAY[v] for v, _, _ in variant_data],
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


def main():
    c2l = load_cluster_to_leaf(CLI_MAP)
    rows = load_labels(CLI_LABELS)

    csv_path = ROOT / "figure7_data.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scope", "variant", "n_failures", "tb_leaf", "group", "prevalence_pct"])

        for scope_label, accepted_apis, basename in RUNS:
            print(f"\n========== {scope_label} ==========")
            variant_data = []
            for v in VARIANTS:
                n, prev = compute_prevalence_for_variant(rows, v, c2l, accepted_apis)
                variant_data.append((v, n, prev))
                print(f"  {v}: n_fair = {n}")
                for leaf in LEAF_PLOT_ORDER:
                    print(f"      {leaf:35s} {prev[leaf]:5.1f}%")
            render(variant_data,
                   ROOT / f"{basename}.pdf",
                   ROOT / f"{basename}.png")
            for v, n, prev in variant_data:
                for leaf in LEAF_PLOT_ORDER:
                    w.writerow([scope_label, v, n, leaf, LEAF_GROUP[leaf],
                                f"{prev[leaf]:.2f}"])
    print(f"\nwrote → {csv_path.name}")


if __name__ == "__main__":
    main()
