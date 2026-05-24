#!/usr/bin/env python3
"""Figure 7B — Per-cluster decomposition of Codex's Disobey Specification
failures: bash_only vs bash_tool.

A trajectory contributes to a cluster if that cluster appears as the primary
OR a secondary in the Phase 3 classification. Display-merged children are
rolled up to their merged parent (matching taxonomy.md).

Style: horizontal grouped bars (clusters on the y-axis sorted by total
prevalence). Two color shades distinguish the variant.
"""
from __future__ import annotations
import csv
import json
import re
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from _render_lib import GUI_ONLY_TASK_IDS, task_id_from_trajectory_id

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent / "2026-05-21_android-cli-failures-combined"
LABELS = WS / "classification/cluster_labels_full.jsonl"
CONSENSUS = WS / "consensus_mapping_v3.json"

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

# Presentation-layer cluster renames (mirror generate_taxonomy_doc.py).
# Raw JSONL keeps the original name; figures render the alias.
CLUSTER_DISPLAY_ALIAS = {
    "task_required_gui_only_no_cli_pathway": "agent_concluded_no_cli_pathway",
}

VARIANT_COLOR = {
    "bash_only": "#3D7CC8",  # blue
    "bash_tool": "#F5A623",  # orange
}


def main():
    consensus = json.load(open(CONSENSUS))["consensus"]
    c2l = {c: m["primary_tb_leaf"] for c, m in consensus.items()}

    data = {"bash_only": [0, Counter()], "bash_tool": [0, Counter()]}
    for ln in open(LABELS):
        o = json.loads(ln)
        if "primary_cluster" not in o:
            continue
        tid = task_id_from_trajectory_id(o["trajectory_id"])
        if tid is None or tid in GUI_ONLY_TASK_IDS:
            continue
        if o.get("model_api") != "openaigpt53codex":
            continue
        v = o.get("action_variant", "?")
        if v not in data:
            continue
        clusters = [o["primary_cluster"]] + list(o.get("secondary_clusters") or [])
        ds_in_traj = set()
        for c in clusters:
            if c2l.get(c) == "Disobey Specification":
                # Apply merges first, then display alias (rename for presentation)
                disp = SRC_TO_MERGED.get(c, c)
                disp = CLUSTER_DISPLAY_ALIAS.get(disp, disp)
                ds_in_traj.add(disp)
        data[v][0] += 1
        for c in ds_in_traj:
            data[v][1][c] += 1

    n_only = data["bash_only"][0]
    n_tool = data["bash_tool"][0]

    all_clusters = sorted(
        set(data["bash_only"][1]) | set(data["bash_tool"][1]),
        key=lambda c: -(data["bash_only"][1][c] / max(n_only, 1)
                        + data["bash_tool"][1][c] / max(n_tool, 1)),
    )
    print(f"Codex × bash_only n={n_only}  ·  Codex × bash_tool n={n_tool}")
    print(f"{'DS sub-cluster':62s} {'bash_only':>11s} {'bash_tool':>11s} {'Δpp':>7s}")
    for c in all_clusters:
        a = data["bash_only"][1][c] / n_only * 100
        b = data["bash_tool"][1][c] / n_tool * 100
        print(f"  {c:60s} {a:9.1f}% {b:9.1f}% {b-a:+6.1f}")

    # --- Render horizontal grouped bars ---
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.labelcolor": "#222",
        "xtick.color": "#222",
        "ytick.color": "#222",
        "axes.edgecolor": "#444",
    })
    fig, ax = plt.subplots(figsize=(12, 7.5))

    n_clusters = len(all_clusters)
    y_pos = list(range(n_clusters))
    bar_h = 0.36

    for i, c in enumerate(all_clusters):
        a = data["bash_only"][1][c] / n_only * 100
        b = data["bash_tool"][1][c] / n_tool * 100
        ax.barh(i + bar_h / 2, a, height=bar_h,
                color=VARIANT_COLOR["bash_only"], edgecolor="#222",
                linewidth=0.6, zorder=3, label="bash_only" if i == 0 else None)
        ax.barh(i - bar_h / 2, b, height=bar_h,
                color=VARIANT_COLOR["bash_tool"], edgecolor="#222",
                linewidth=0.6, zorder=3, label="bash_tool" if i == 0 else None)
        if a >= 0.5:
            ax.text(a + 0.6, i + bar_h / 2, f"{a:.0f}%", ha="left", va="center",
                    fontsize=9, color="#333")
        if b >= 0.5:
            ax.text(b + 0.6, i - bar_h / 2, f"{b:.0f}%", ha="left", va="center",
                    fontsize=9, color="#333")

    # Pretty cluster labels (display-merged with a ◇ marker)
    def label_for(c):
        marker = " ◇" if c in DISPLAY_MERGES else ""
        return c.replace("_", " ") + marker

    ax.set_yticks(y_pos)
    ax.set_yticklabels([label_for(c) for c in all_clusters], fontsize=10.5)
    ax.tick_params(axis="y", which="both", length=0, pad=4)
    ax.invert_yaxis()

    ax.set_xlim(0, 50)
    ax.set_xticks(range(0, 51, 10))
    ax.tick_params(axis="x", which="both", length=0, labelsize=10)
    ax.set_xlabel("Prevalence within Codex failures (%)", fontsize=11)
    ax.grid(axis="x", alpha=0.35, linestyle=(0, (4, 4)), linewidth=0.6,
            color="#999", zorder=1)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#444")
    ax.spines["bottom"].set_linewidth(0.8)

    legend_handles = [
        mpatches.Patch(facecolor=VARIANT_COLOR["bash_only"],
                       edgecolor="#222", linewidth=0.6, label="bash_only"),
        mpatches.Patch(facecolor=VARIANT_COLOR["bash_tool"],
                       edgecolor="#222", linewidth=0.6,
                       label="bash_tool (+ tool wrapper)"),
        mpatches.Patch(color="none", label="◇ display-merged cluster"),
    ]
    leg = ax.legend(handles=legend_handles, loc="lower right",
                    fontsize=10, frameon=True, handlelength=2.0,
                    borderpad=0.8, labelspacing=0.5)
    leg.get_frame().set_edgecolor("#bbb")
    leg.get_frame().set_linewidth(0.8)
    leg.get_frame().set_facecolor("#fafafa")

    fig.tight_layout()
    out_pdf = ROOT / "figure7b_codex_ds_clusters.pdf"
    out_png = ROOT / "figure7b_codex_ds_clusters.png"
    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=200, bbox_inches="tight")
    print(f"\nsaved → {out_pdf.name}, {out_png.name}")

    with (ROOT / "figure7b_data.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "n_failures", "ds_cluster", "n_with_cluster",
                    "prevalence_pct"])
        for v in ("bash_only", "bash_tool"):
            n, cnt = data[v]
            for c in all_clusters:
                w.writerow([v, n, c, cnt[c], f"{cnt[c]/n*100:.2f}"])
    print("wrote → figure7b_data.csv")


if __name__ == "__main__":
    main()
