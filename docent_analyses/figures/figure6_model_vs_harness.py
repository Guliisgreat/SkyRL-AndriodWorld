#!/usr/bin/env python3
"""Figure 6 — Three composite views of "model vs harness" for the CLI paradigm.

Each variant tells the same story (model identity drives the failure profile;
harness is a secondary modifier) but emphasizes a different visual cut.

  6A — compound grouped bars (7 harness-columns × 4 leaves, model bands)
  6B — small multiples (1×3 panel, one sub-plot per model)
  6C — heatmap (4 leaves × 7 cells, color = prevalence, model bands)

Fair-view only (13 GUI-only AndroidWorld tasks excluded). Active leaves are the
four with nonzero prevalence somewhere in the data:
  Disobey Specification, Reasoning-Action Mismatch,
  Premature Termination, Weak Verification
"""
from __future__ import annotations
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap

from _render_lib import load_cluster_to_leaf, load_labels
from figure4_paradigm_tb_grouped import (
    LEAF_GROUP, GROUP_COLOR, LEAF_HATCH,
)
from figure5_one_api_three_harnesses import (
    compute_prevalence_for_harness, CLI_LABELS, CLI_MAP, MODEL_VARIANTS,
    SHARED_HARNESS_ORDER,
)

ROOT = Path(__file__).resolve().parent

# Bars/columns in display order: drop Step Repetition + 4 other leaves that are
# 0% everywhere in the CLI paradigm.
ACTIVE_LEAVES = [
    "Disobey Specification",
    "Reasoning-Action Mismatch",
    "Premature Termination",
    "Weak Verification",
]

# Friendlier short model labels for the figure
MODEL_DISPLAY = {
    "claude-sonnet-4.6": "Claude Sonnet 4.6",
    "gpt-5.3-codex":     "GPT-5.3 Codex",
    "minimax-m2.7":      "MiniMax M2.7",
}


def common_rc():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.labelcolor": "#222",
        "xtick.color": "#222",
        "ytick.color": "#222",
        "axes.edgecolor": "#444",
    })


def collect_cells(rows, c2l):
    """Return list of (model_label, harness, n, prev_dict) cells with n>0,
    in the canonical (model × harness) order from MODEL_VARIANTS."""
    cells = []
    for model_label, accepted_apis, _ in MODEL_VARIANTS:
        for h in SHARED_HARNESS_ORDER:
            n, prev = compute_prevalence_for_harness(rows, h, accepted_apis, c2l)
            if n == 0:
                continue
            cells.append((model_label, h, n, prev))
    return cells


# ---------------------------------------------------------------------------
# 6A. Compound grouped bars
# ---------------------------------------------------------------------------
def render_compound(cells, out_pdf, out_png):
    common_rc()
    fig, ax = plt.subplots(figsize=(15, 6))

    n_leaves = len(ACTIVE_LEAVES)
    bar_width = 0.075
    intra_gap = 0.015
    pitch = bar_width + intra_gap
    col_span = n_leaves * pitch - intra_gap
    col_gap = col_span * 0.55          # gap between harnesses inside a model
    model_gap = col_span * 1.6          # bigger gap between models

    # Compute column starts grouped by model
    col_starts = []
    col_models = [c[0] for c in cells]
    x = 0.0
    prev_model = None
    for m in col_models:
        if prev_model is None:
            pass
        elif m == prev_model:
            x += col_span + col_gap
        else:
            x += col_span + model_gap
        col_starts.append(x)
        prev_model = m

    # Draw bars
    for col_idx, (_, harness, n_traj, prev) in enumerate(cells):
        for li, leaf in enumerate(ACTIVE_LEAVES):
            group = LEAF_GROUP[leaf]
            color = GROUP_COLOR[group]
            hatch = LEAF_HATCH[leaf]
            xb = col_starts[col_idx] + li * pitch
            h = prev[leaf]
            ax.bar(xb, h, width=bar_width, color=color,
                   edgecolor="#222", linewidth=0.7, hatch=hatch, zorder=3)
            if h >= 1.0:
                ax.text(xb, h + 1.5, f"{h:.0f}%", ha="center", va="bottom",
                        fontsize=8, color="#333", zorder=4)

    # Harness labels (under each column)
    col_centers = [s + (col_span - bar_width) / 2 + bar_width / 2
                   for s in col_starts]
    ax.set_xticks(col_centers)
    ax.set_xticklabels([h for _, h, _, _ in cells], fontsize=10.5)
    ax.tick_params(axis="x", which="both", length=0, pad=6)

    # Model-band labels above the bars + thin vertical dividers between models
    model_groups = []
    cur_model = None
    cur_starts = []
    for i, m in enumerate(col_models):
        if m != cur_model:
            if cur_model is not None:
                model_groups.append((cur_model, cur_starts))
            cur_model = m
            cur_starts = [i]
        else:
            cur_starts.append(i)
    if cur_model is not None:
        model_groups.append((cur_model, cur_starts))

    ymax = 100
    for gi, (m, idxs) in enumerate(model_groups):
        left = col_starts[idxs[0]] - bar_width * 0.6
        right = col_starts[idxs[-1]] + col_span + bar_width * 0.6
        mid = (left + right) / 2
        # Soft band underlay
        band_color = "#f4f6fa" if gi % 2 == 0 else "#eef1f5"
        ax.axvspan(left - bar_width * 0.3, right + bar_width * 0.3,
                   color=band_color, alpha=0.6, zorder=0)
        ax.text(mid, ymax + 4, MODEL_DISPLAY[m], ha="center", va="bottom",
                fontsize=12, fontweight="bold", color="#222")

    # Divider lines between models
    for (m1, idxs1), (m2, idxs2) in zip(model_groups, model_groups[1:]):
        x_div = (col_starts[idxs1[-1]] + col_span
                 + col_starts[idxs2[0]]) / 2
        ax.axvline(x_div, color="#bbb", linewidth=0.7, linestyle=":",
                   zorder=1)

    ax.set_ylim(0, 110)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Failure prevalence (%)", fontsize=12)
    ax.tick_params(axis="y", length=0, labelsize=10)
    ax.grid(axis="y", alpha=0.3, linestyle=(0, (4, 4)), linewidth=0.6,
            color="#999", zorder=1)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#444")
    ax.spines["bottom"].set_linewidth(0.8)
    ax.set_xlim(col_starts[0] - bar_width * 2,
                col_starts[-1] + col_span + bar_width * 2)

    # Legend (TB-paper grouping)
    legend_handles = []
    last_group = None
    for leaf in ACTIVE_LEAVES:
        group = LEAF_GROUP[leaf]
        if group != last_group:
            legend_handles.append(mpatches.Patch(
                color="none", label=f"$\\bf{{{group}}}$"))
            last_group = group
        legend_handles.append(mpatches.Patch(
            facecolor=GROUP_COLOR[group], edgecolor="#222",
            linewidth=0.7, hatch=LEAF_HATCH[leaf], label=f"  {leaf}"))
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


# ---------------------------------------------------------------------------
# 6B. Small multiples (1 × 3 panel, one sub-plot per model)
# ---------------------------------------------------------------------------
def render_small_multiples(cells, out_pdf, out_png):
    common_rc()
    # Bucket cells by model
    by_model: dict[str, list] = {}
    for (m, h, n, p) in cells:
        by_model.setdefault(m, []).append((h, n, p))

    model_order = [m for m, _, _ in MODEL_VARIANTS]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.5), sharey=True,
                             gridspec_kw={"wspace": 0.18})
    n_leaves = len(ACTIVE_LEAVES)
    bar_width = 0.095
    intra_gap = 0.02
    pitch = bar_width + intra_gap
    group_span = n_leaves * pitch - intra_gap
    group_gap = group_span * 0.55

    for ax_idx, model in enumerate(model_order):
        ax = axes[ax_idx]
        harnesses = by_model.get(model, [])
        # Always use the SHARED_HARNESS_ORDER positions; missing → no-runs label
        h_data_by_name = {h: (n, p) for h, n, p in harnesses}
        n_groups = len(SHARED_HARNESS_ORDER)
        group_starts = [i * (group_span + group_gap) for i in range(n_groups)]
        for grp_idx, h in enumerate(SHARED_HARNESS_ORDER):
            if h not in h_data_by_name:
                mid_x = group_starts[grp_idx] + (group_span - bar_width) / 2
                ax.text(mid_x, 50, "no runs", ha="center", va="center",
                        fontsize=10, color="#888", style="italic")
                continue
            _, prev = h_data_by_name[h]
            for li, leaf in enumerate(ACTIVE_LEAVES):
                group = LEAF_GROUP[leaf]
                color = GROUP_COLOR[group]
                hatch = LEAF_HATCH[leaf]
                xb = group_starts[grp_idx] + li * pitch
                h_val = prev[leaf]
                ax.bar(xb, h_val, width=bar_width, color=color,
                       edgecolor="#222", linewidth=0.6, hatch=hatch, zorder=3)
                if h_val >= 1.0:
                    ax.text(xb, h_val + 1.3, f"{h_val:.0f}%",
                            ha="center", va="bottom",
                            fontsize=7.5, color="#333", zorder=4)

        # Harness labels
        group_centers = [s + (group_span - bar_width) / 2 + bar_width / 2
                         for s in group_starts]
        ax.set_xticks(group_centers)
        ax.set_xticklabels(SHARED_HARNESS_ORDER, fontsize=10)
        ax.tick_params(axis="x", length=0, pad=6)
        ax.set_xlim(group_starts[0] - bar_width,
                    group_starts[-1] + group_span + bar_width)

        ax.set_title(MODEL_DISPLAY[model], fontsize=12,
                     fontweight="bold", pad=10, color="#222")
        if ax_idx == 0:
            ax.set_ylabel("Failure prevalence (%)", fontsize=12)
        ax.set_ylim(0, 105)
        ax.set_yticks(range(0, 101, 20))
        ax.tick_params(axis="y", length=0, labelsize=10)
        ax.grid(axis="y", alpha=0.3, linestyle=(0, (4, 4)), linewidth=0.6,
                color="#999", zorder=1)
        ax.set_axisbelow(True)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color("#444")
        ax.spines["bottom"].set_linewidth(0.8)

    # Single shared legend on the right
    legend_handles = []
    last_group = None
    for leaf in ACTIVE_LEAVES:
        group = LEAF_GROUP[leaf]
        if group != last_group:
            legend_handles.append(mpatches.Patch(
                color="none", label=f"$\\bf{{{group}}}$"))
            last_group = group
        legend_handles.append(mpatches.Patch(
            facecolor=GROUP_COLOR[group], edgecolor="#222",
            linewidth=0.7, hatch=LEAF_HATCH[leaf], label=f"  {leaf}"))
    leg = fig.legend(handles=legend_handles, loc="center right",
                     bbox_to_anchor=(1.0, 0.5), fontsize=10,
                     frameon=True, handlelength=2.2, handleheight=1.4,
                     borderpad=0.9, labelspacing=0.55)
    leg.get_frame().set_edgecolor("#bbb")
    leg.get_frame().set_linewidth(0.8)
    leg.get_frame().set_facecolor("#fafafa")

    fig.tight_layout(rect=(0, 0, 0.88, 1))
    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=200, bbox_inches="tight")
    print(f"saved → {out_pdf.name}, {out_png.name}")


# ---------------------------------------------------------------------------
# 6C. Heatmap (4 leaves × 7 cells, color = prevalence)
# ---------------------------------------------------------------------------
def render_heatmap(cells, out_pdf, out_png):
    common_rc()
    # Build a row per leaf, column per cell. Skip cells with n==0.
    cols = cells
    n_cols = len(cols)
    n_rows = len(ACTIVE_LEAVES)
    data = [[cells[ci][3][leaf] for ci in range(n_cols)]
            for leaf in ACTIVE_LEAVES]

    fig, ax = plt.subplots(figsize=(11, 4.2))

    # Continuous colormap white → deep blue
    cmap = LinearSegmentedColormap.from_list(
        "blueheat", ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"])
    im = ax.imshow(data, cmap=cmap, vmin=0, vmax=100, aspect="auto",
                   origin="upper")

    # Cell annotations
    for r in range(n_rows):
        for c in range(n_cols):
            v = data[r][c]
            txt_color = "white" if v >= 55 else "#222"
            ax.text(c, r, f"{v:.0f}%", ha="center", va="center",
                    fontsize=11, color=txt_color, fontweight="semibold")

    # Y-axis: leaf names, colored by TB group
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(ACTIVE_LEAVES, fontsize=11)
    for i, lbl in enumerate(ax.get_yticklabels()):
        lbl.set_color(GROUP_COLOR[LEAF_GROUP[ACTIVE_LEAVES[i]]])
        lbl.set_fontweight("semibold")
    ax.tick_params(axis="y", length=0, pad=4)

    # X-axis (bottom): harness labels
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels([cells[c][1] for c in range(n_cols)],
                       fontsize=10, rotation=0)
    ax.tick_params(axis="x", length=0, pad=4)

    # Model-band labels above the columns + dividing lines
    model_groups = []
    cur_model = None
    cur_idxs = []
    for i, c in enumerate(cells):
        m = c[0]
        if m != cur_model:
            if cur_model is not None:
                model_groups.append((cur_model, cur_idxs))
            cur_model = m
            cur_idxs = [i]
        else:
            cur_idxs.append(i)
    if cur_model is not None:
        model_groups.append((cur_model, cur_idxs))

    for m, idxs in model_groups:
        left = idxs[0] - 0.5
        right = idxs[-1] + 0.5
        ax.text((left + right) / 2, -0.9, MODEL_DISPLAY[m],
                ha="center", va="bottom",
                fontsize=12, fontweight="bold", color="#222")

    # Thin vertical dividers between model bands
    for (m1, idxs1), (m2, idxs2) in zip(model_groups, model_groups[1:]):
        x_div = idxs1[-1] + 0.5
        ax.axvline(x_div, color="white", linewidth=2.5)

    # Cosmetic frame
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.set_xlim(-0.5, n_cols - 0.5)
    ax.set_ylim(n_rows - 0.5, -0.5)
    # Extra top space for model labels
    ax.set_ylim(top=-1.4)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.025,
                        ticks=[0, 25, 50, 75, 100])
    cbar.outline.set_visible(False)
    cbar.ax.set_ylabel("Failure prevalence (%)", fontsize=10)
    cbar.ax.tick_params(length=0, labelsize=9)

    fig.tight_layout()
    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=200, bbox_inches="tight")
    print(f"saved → {out_pdf.name}, {out_png.name}")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main():
    c2l = load_cluster_to_leaf(CLI_MAP)
    rows = load_labels(CLI_LABELS)
    cells = collect_cells(rows, c2l)
    print(f"populated cells (model × harness): {len(cells)}")
    for m, h, n, _ in cells:
        print(f"  {m:18s} × {h:14s}  n={n}")

    render_compound(cells,
                    ROOT / "figure6A_compound_groups.pdf",
                    ROOT / "figure6A_compound_groups.png")
    render_small_multiples(cells,
                           ROOT / "figure6B_small_multiples.pdf",
                           ROOT / "figure6B_small_multiples.png")
    render_heatmap(cells,
                   ROOT / "figure6C_heatmap.pdf",
                   ROOT / "figure6C_heatmap.png")

    # Long-form CSV for all 3 variants
    out_csv = ROOT / "figure6_data.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "harness", "n_failures", "tb_leaf", "group",
                    "prevalence_pct"])
        for m, h, n, prev in cells:
            for leaf in ACTIVE_LEAVES:
                w.writerow([m, h, n, leaf, LEAF_GROUP[leaf],
                            f"{prev[leaf]:.2f}"])
    print(f"wrote → {out_csv.name}")


if __name__ == "__main__":
    main()
