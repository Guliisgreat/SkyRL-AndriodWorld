#!/usr/bin/env python3
"""Figure 7 (composite) — Codex × bash_only vs bash_tool.

Two stacked panels:
  (a) TB-leaf level — 4 active leaves × 2 variants, mirroring figure 7's
      single-model panel (Codex only).
  (b) DS-cluster-level divergence — horizontal Δ-pp bars per DS sub-cluster.
      Negative (left) = wrapper helps; positive (right) = wrapper hurts /
      no benefit. Clusters ordered top-to-bottom from largest help to
      largest hurt.

Both panels are restricted to fair view (13 GUI-only tasks excluded) and to
trajectories with `model_api == openaigpt53codex`. Cluster names are renamed
to their display alias (e.g. agent_concluded_no_cli_pathway).
"""
from __future__ import annotations
import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec

from _render_lib import (
    GUI_ONLY_TASK_IDS, task_id_from_trajectory_id,
    load_cluster_to_leaf, load_labels, normalize_leaf,
)
from figure4_paradigm_tb_grouped import (
    LEAF_PLOT_ORDER, LEAF_GROUP, GROUP_COLOR, LEAF_HATCH,
)

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent / "2026-05-21_android-cli-failures-combined"
LABELS = WS / "classification/cluster_labels_full.jsonl"
CONSENSUS_PATH = WS / "consensus_mapping_v3.json"

DISPLAY_MERGES = {
    "wrapper_input_format_violation": {
        "shell_quoting_or_harness_parse_blocked_action",
        "harness_verb_or_command_prefix_violation",
    },
    "wrong_output_value_at_correct_surface": {
        "time_or_timezone_misinterpretation",
        "recurrence_or_filter_predicate_omission",
        "byte_exact_file_content_mismatch",
    },
}
SRC_TO_MERGED = {s: m for m, ss in DISPLAY_MERGES.items() for s in ss}

CLUSTER_DISPLAY_ALIAS = {
    "task_required_gui_only_no_cli_pathway": "agent_concluded_no_cli_pathway",
}

# Colors: blue for bash_only / "wrapper helps", orange for bash_tool /
# "wrapper hurts (or grows engagement w/ blocked surfaces)"
COLOR_HELP = "#3D7CC8"   # blue
COLOR_HURT = "#F5A623"   # orange


def compute_codex_data(c2l: dict) -> tuple[dict, dict]:
    """Return ({variant: (n, leaf_prev)}, {variant: (n, ds_cluster_prev)})."""
    leaf_data = {"bash_only": [0, Counter()], "bash_tool": [0, Counter()]}
    ds_data   = {"bash_only": [0, Counter()], "bash_tool": [0, Counter()]}
    for r in load_labels(LABELS):
        if r.get("model_api") != "openaigpt53codex":
            continue
        v = r.get("action_variant")
        if v not in leaf_data:
            continue
        tid = task_id_from_trajectory_id(r.get("trajectory_id", ""))
        if tid is None or tid in GUI_ONLY_TASK_IDS:
            continue
        clusters = [r["primary_cluster"]] + list(r.get("secondary_clusters") or [])
        leaves_in_traj = set()
        ds_in_traj = set()
        for c in clusters:
            if c in c2l:
                leaf = normalize_leaf(c2l[c])
                leaves_in_traj.add(leaf)
                if leaf == "Disobey Specification":
                    disp = SRC_TO_MERGED.get(c, c)
                    disp = CLUSTER_DISPLAY_ALIAS.get(disp, disp)
                    ds_in_traj.add(disp)
        leaf_data[v][0] += 1
        ds_data[v][0]   += 1
        for l in leaves_in_traj:
            leaf_data[v][1][l] += 1
        for c in ds_in_traj:
            ds_data[v][1][c] += 1
    return leaf_data, ds_data


def render(leaf_data: dict, ds_data: dict, out_pdf: Path, out_png: Path) -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.labelcolor": "#222",
        "xtick.color": "#222",
        "ytick.color": "#222",
        "axes.edgecolor": "#444",
    })

    n_only = leaf_data["bash_only"][0]
    n_tool = leaf_data["bash_tool"][0]
    leaf_pct = {
        v: {l: (leaf_data[v][1][l] / max(leaf_data[v][0], 1) * 100)
            for l in LEAF_PLOT_ORDER}
        for v in ("bash_only", "bash_tool")
    }
    active_leaves = [l for l in LEAF_PLOT_ORDER
                     if leaf_pct["bash_only"][l] > 0 or leaf_pct["bash_tool"][l] > 0]

    # DS-cluster level: union of clusters, sorted by Δ pp (help → hurt)
    all_clusters = sorted(
        set(ds_data["bash_only"][1]) | set(ds_data["bash_tool"][1])
    )
    cluster_rows = []
    for c in all_clusters:
        a = ds_data["bash_only"][1][c] / max(ds_data["bash_only"][0], 1) * 100
        b = ds_data["bash_tool"][1][c] / max(ds_data["bash_tool"][0], 1) * 100
        cluster_rows.append((c, a, b, b - a))
    # Sort so the top of the chart = wrapper helps the most (most negative Δ),
    # bottom = wrapper hurts the most (most positive Δ).
    cluster_rows.sort(key=lambda r: r[3])

    fig = plt.figure(figsize=(11.5, 8.5))
    gs = gridspec.GridSpec(2, 1, height_ratios=[1.0, 1.7], hspace=0.42)

    # --- Panel (a): TB-leaf level ---
    ax_a = fig.add_subplot(gs[0])
    n_leaves = len(active_leaves)
    bar_width = 0.075
    intra_gap = 0.015
    pitch = bar_width + intra_gap
    group_span = n_leaves * pitch - intra_gap
    group_gap = group_span * 1.4
    group_starts = [0.0, group_span + group_gap]
    bar_positions = [[s + i * pitch for i in range(n_leaves)] for s in group_starts]

    variant_list = [("bash_only", n_only, leaf_pct["bash_only"]),
                    ("bash_tool", n_tool, leaf_pct["bash_tool"])]
    for grp_idx, (_, _, prev) in enumerate(variant_list):
        for li, leaf in enumerate(active_leaves):
            group = LEAF_GROUP[leaf]
            color = GROUP_COLOR[group]
            hatch = LEAF_HATCH[leaf]
            x = bar_positions[grp_idx][li]
            h = prev[leaf]
            ax_a.bar(x, h, width=bar_width, color=color,
                     edgecolor="#222", linewidth=0.7, hatch=hatch, zorder=3)
            if h >= 1.0:
                ax_a.text(x, h + 1.8, f"{h:.0f}%", ha="center", va="bottom",
                          fontsize=9, color="#333", zorder=4)

    group_label_x = [
        (bar_positions[i][0] + bar_positions[i][-1]) / 2
        for i in range(2)
    ]
    ax_a.set_xticks(group_label_x)
    ax_a.set_xticklabels(["bash_only", "bash_tool (+ tool wrapper)"],
                         fontsize=12, fontweight="bold")
    ax_a.tick_params(axis="x", which="both", length=0, pad=6)
    side_pad = group_span * 0.6
    ax_a.set_xlim(bar_positions[0][0] - side_pad,
                  bar_positions[-1][-1] + bar_width + side_pad)
    ax_a.set_ylabel("Failure prevalence (%)", fontsize=11)
    ax_a.set_ylim(0, 100)
    ax_a.set_yticks(range(0, 101, 20))
    ax_a.tick_params(axis="y", which="both", length=0, labelsize=10)
    ax_a.grid(axis="y", alpha=0.35, linestyle=(0, (4, 4)), linewidth=0.6,
              color="#999", zorder=1)
    ax_a.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax_a.spines[s].set_visible(False)
    ax_a.spines["bottom"].set_color("#444")
    ax_a.spines["bottom"].set_linewidth(0.8)
    ax_a.text(-0.07, 1.05, "(a)  TB-leaf level",
              transform=ax_a.transAxes, ha="left", va="bottom",
              fontsize=13, fontweight="bold", color="#222")

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
            linewidth=0.7, hatch=LEAF_HATCH[leaf], label=f"  {leaf}"))
    leg_a = ax_a.legend(handles=legend_handles, loc="center left",
                        bbox_to_anchor=(1.015, 0.5), fontsize=9.5,
                        frameon=True, handlelength=2.2, handleheight=1.4,
                        borderpad=0.7, labelspacing=0.4)
    leg_a.get_frame().set_edgecolor("#bbb")
    leg_a.get_frame().set_linewidth(0.8)
    leg_a.get_frame().set_facecolor("#fafafa")

    # --- Panel (b): DS-cluster Δ-pp divergence ---
    ax_b = fig.add_subplot(gs[1])
    n_rows = len(cluster_rows)
    y_pos = list(range(n_rows))
    bar_h = 0.6

    max_abs = max(abs(r[3]) for r in cluster_rows)
    # Reserve right-margin space for the "x% → y%" annotation column
    label_x = max_abs * 1.05 + 1.0
    x_lim_right = label_x + 4.0
    x_lim_left = max_abs * 1.2 + 0.5

    for i, (name, a, b, delta) in enumerate(cluster_rows):
        color = COLOR_HELP if delta < 0 else COLOR_HURT
        ax_b.barh(i, delta, height=bar_h, color=color,
                  edgecolor="#222", linewidth=0.6, zorder=3)
        # Δ annotation (just outside the bar tip)
        sign = "+" if delta > 0 else "−" if delta < 0 else "±"
        txt = f"{sign}{abs(delta):.1f} pp"
        offset = 0.4 if delta >= 0 else -0.4
        ha = "left" if delta >= 0 else "right"
        ax_b.text(delta + offset, i, txt, ha=ha, va="center",
                  fontsize=9, color="#222", zorder=4)
        # Right-margin column: absolute prevalence "bash_only → bash_tool"
        ax_b.text(label_x, i,
                  f"{a:.0f}% → {b:.0f}%",
                  ha="left", va="center", fontsize=9,
                  color="#666", style="italic", zorder=4)

    def pretty(name: str) -> str:
        marker = " ◇" if name in DISPLAY_MERGES else ""
        return name.replace("_", " ") + marker

    ax_b.set_yticks(y_pos)
    ax_b.set_yticklabels([pretty(name) for name, _, _, _ in cluster_rows],
                         fontsize=10.5)
    ax_b.tick_params(axis="y", which="both", length=0, pad=4)
    ax_b.invert_yaxis()  # so top of chart = wrapper helps most

    ax_b.axvline(0, color="#444", linewidth=0.8, zorder=2)
    ax_b.set_xlim(-x_lim_left, x_lim_right)
    # Only mark Δ-axis ticks (not the right-margin annotation column)
    tick_max = int((max_abs // 5 + 1) * 5)
    ticks = list(range(-tick_max, tick_max + 1, 5))
    ax_b.set_xticks(ticks)
    ax_b.set_xticklabels([f"{t:+d}" if t != 0 else "0" for t in ticks])
    ax_b.set_xlabel("Δ prevalence under bash_tool (percentage points)",
                    fontsize=11)
    ax_b.tick_params(axis="x", length=0, labelsize=10)
    ax_b.grid(axis="x", alpha=0.3, linestyle=(0, (4, 4)), linewidth=0.6,
              color="#999", zorder=1)
    ax_b.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax_b.spines[s].set_visible(False)
    ax_b.spines["bottom"].set_color("#444")
    ax_b.spines["bottom"].set_linewidth(0.8)
    ax_b.text(-0.34, 1.10, "(b)  Disobey-Specification sub-clusters (Δ pp)",
              transform=ax_b.transAxes, ha="left", va="bottom",
              fontsize=13, fontweight="bold", color="#222")

    # Direction-of-effect headers, above the bars
    ax_b.text(-x_lim_left * 0.55, n_rows - 0.4 + (-n_rows - 0.5),
              "← bash_tool helps (fewer failures)",
              ha="center", va="bottom", fontsize=9.5,
              color=COLOR_HELP, fontweight="semibold")
    ax_b.text(+max_abs * 0.45, n_rows - 0.4 + (-n_rows - 0.5),
              "bash_tool hurts / no benefit →",
              ha="center", va="bottom", fontsize=9.5,
              color=COLOR_HURT, fontweight="semibold")

    # Per-cluster prevalence header (above the right-margin column)
    ax_b.text(label_x, n_rows - 0.4 + (-n_rows - 0.5),
              "bash_only → bash_tool",
              ha="left", va="bottom",
              fontsize=9, color="#666", style="italic")

    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=200, bbox_inches="tight")
    print(f"saved → {out_pdf.name}, {out_png.name}")


def main():
    c2l = load_cluster_to_leaf(CONSENSUS_PATH)
    leaf_data, ds_data = compute_codex_data(c2l)
    print(f"Codex bash_only n={leaf_data['bash_only'][0]}  "
          f"bash_tool n={leaf_data['bash_tool'][0]}")
    render(leaf_data, ds_data,
           ROOT / "figure7_codex_composite.pdf",
           ROOT / "figure7_codex_composite.png")
    with (ROOT / "figure7_composite_data.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["panel", "variant", "n_failures", "name",
                    "prevalence_pct"])
        for v, (n, lt) in leaf_data.items():
            for leaf in LEAF_PLOT_ORDER:
                w.writerow(["a_leaf", v, n, leaf,
                            f"{lt[leaf] / max(n, 1) * 100:.2f}"])
        for v, (n, ct) in ds_data.items():
            for name, cnt in ct.most_common():
                w.writerow(["b_ds_cluster", v, n, name,
                            f"{cnt / max(n, 1) * 100:.2f}"])
    print("wrote → figure7_composite_data.csv")


if __name__ == "__main__":
    main()
