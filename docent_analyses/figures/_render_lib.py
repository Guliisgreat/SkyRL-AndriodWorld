"""Shared rendering utilities for Figures 1/2/3 — consistent visual style."""
from __future__ import annotations
import json
import re
from collections import Counter
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


# AndroidWorld GUI-only task IDs (no CLI/shell pathway). Source:
# androidworld_ground_truth_reference_final_1.md
GUI_ONLY_TASK_IDS = {0, 8, 20, 28, 29, 30, 37, 47, 55, 75, 76, 78, 80}
_TID_RE = re.compile(r"__t(\d+)$")


def task_id_from_trajectory_id(tid: str) -> int | None:
    m = _TID_RE.search(tid)
    return int(m.group(1)) if m else None


def filter_to_cli_solvable(rows: list[dict]) -> list[dict]:
    """Drop trajectories whose task_id is in GUI_ONLY_TASK_IDS.
    Used for fair cross-paradigm comparison."""
    out = []
    for r in rows:
        tid = task_id_from_trajectory_id(r.get("trajectory_id", ""))
        if tid is not None and tid not in GUI_ONLY_TASK_IDS:
            out.append(r)
    return out


# Per-trajectory leaf overrides — none active.
#
# History: the 2026-05-23 raw-trajectory audit flagged 2 of 212 CLI shell-quoting
# trajectories as RAM (reasoning specified the right command, emitted bytes had
# a quoting bug). Per cluster-level convention, `wrapper_input_format_violation`
# is treated as a single DS leaf (TB11 rev: wrapper input format → DS), so
# those per-trajectory verdicts are no longer applied. The audit JSONL files
# remain for traceability:
#   docent_analyses/2026-05-21_android-cli-failures-combined/validation/ds_audit_cli_raw.jsonl
PER_TRAJECTORY_LEAF_OVERRIDES: dict[str, str] = {}


def effective_leaf(row: dict, cluster_to_leaf: dict) -> str:
    """Return the TB leaf for a per-trajectory row, honoring overrides."""
    tid = row.get("trajectory_id")
    if tid in PER_TRAJECTORY_LEAF_OVERRIDES:
        return PER_TRAJECTORY_LEAF_OVERRIDES[tid]
    return cluster_to_leaf.get(row["primary_cluster"], "?")


GROUP_COLORS = {
    "Execution":    "#1f77b4",  # blue
    "Coherence":    "#d62728",  # red
    "Verification": "#ff9f1c",  # amber
    "Out-of-Scope": "#7f7f7f",  # gray
}

LEAF_GROUP = {
    "Disobey Specification":        "Execution",
    "Step Repetition":              "Execution",
    "Unaware of Termination":       "Execution",
    "Reasoning-Action Mismatch":    "Coherence",
    "Context Loss":                 "Coherence",
    "Task Derailment":              "Coherence",
    "Premature Termination":        "Verification",
    "Weak Verification":            "Verification",
    "No or Incorrect Verification": "Verification",
    "(not in TB)":                  "Out-of-Scope",
}

LEAF_HATCH = {
    "Disobey Specification":        "",
    "Step Repetition":              "////",
    "Unaware of Termination":       "....",
    "Reasoning-Action Mismatch":    "",
    "Context Loss":                 "////",
    "Task Derailment":              "....",
    "Premature Termination":        "",
    "Weak Verification":            "////",
    "No or Incorrect Verification": "....",
    "(not in TB)":                  "xxxx",
}

LEAF_ORDER = [
    "Disobey Specification",
    "Step Repetition",
    "Unaware of Termination",
    "Reasoning-Action Mismatch",
    "Context Loss",
    "Task Derailment",
    "Premature Termination",
    "Weak Verification",
    "No or Incorrect Verification",
    "(not in TB)",
]


def normalize_leaf(leaf: str) -> str:
    leaf = leaf.strip().replace("–", "-").replace("—", "-")
    low = leaf.lower()
    if low.startswith("(not in tb") or low.startswith("not in tb"):
        return "(not in TB)"
    if low.startswith("reasoning") and "action" in low and "mismatch" in low:
        return "Reasoning-Action Mismatch"
    if low.startswith("unaware") and "termination" in low:
        return "Unaware of Termination"
    return leaf


def load_cluster_to_leaf(consensus_path: Path) -> dict[str, str]:
    consensus = json.loads(consensus_path.read_text())["consensus"]
    return {c: normalize_leaf(m["primary_tb_leaf"]) for c, m in consensus.items()}


def load_labels(labels_path: Path) -> list[dict]:
    rows = []
    for line in labels_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if "error" not in r:
                rows.append(r)
        except Exception:
            pass
    return rows


def leaf_distribution(rows: list[dict], cluster_to_leaf: dict) -> tuple[int, dict]:
    """Compute TB-leaf distribution. Honors PER_TRAJECTORY_LEAF_OVERRIDES."""
    n = len(rows)
    leaf_counts = Counter()
    for r in rows:
        leaf = effective_leaf(r, cluster_to_leaf)
        leaf = normalize_leaf(leaf)
        leaf_counts[leaf] += 1
    return n, {leaf: leaf_counts[leaf] / n * 100 for leaf in leaf_counts}


def render_stacked_bars(columns: list[tuple], title: str, x_subtitles: list[str],
                        out_pdf: Path, out_png: Path, figsize=(11, 9),
                        title_pad: int = 15, extra_footer: str | None = None) -> None:
    """columns: list of (label, n_trajs, leaf_dist) tuples — each becomes one stacked bar.
    x_subtitles: per-column x-axis label text (with newline allowed)."""
    fig, ax = plt.subplots(figsize=figsize)
    n_cols = len(columns)
    bar_width = 0.55
    x_positions = list(range(n_cols))

    leaves_present = set()
    for _, _, dist in columns:
        leaves_present.update(k for k, v in dist.items() if v > 0)

    for col_idx, (label, n, dist) in enumerate(columns):
        x_pos = x_positions[col_idx]
        bottom = 0.0
        for leaf in LEAF_ORDER:
            share = dist.get(leaf, 0.0)
            if share <= 0:
                continue
            group = LEAF_GROUP.get(leaf, "Out-of-Scope")
            color = GROUP_COLORS[group]
            hatch = LEAF_HATCH.get(leaf, "")
            ax.bar(x_pos, share, width=bar_width, bottom=bottom,
                   color=color, edgecolor="black", linewidth=1.0,
                   hatch=hatch)
            if share >= 4.0:
                ax.text(x_pos, bottom + share / 2,
                        f"{leaf}\n{share:.1f}%",
                        ha="center", va="center",
                        fontsize=9, fontweight="bold",
                        color="white" if group in ("Execution", "Coherence")
                              else "black")
            elif share >= 1.0:
                # callout to the side (alternate left/right)
                side = "right" if col_idx == n_cols - 1 else "left"
                offset = -0.32 if side == "left" else 0.32
                xy_anchor_x = x_pos + (bar_width / 2 if side == "left" else -bar_width / 2)
                ax.annotate(f"{leaf} ({share:.1f}%)",
                            xy=(xy_anchor_x, bottom + share / 2),
                            xytext=(x_pos + offset, bottom + share / 2),
                            ha="right" if side == "left" else "left",
                            va="center", fontsize=8,
                            arrowprops=dict(arrowstyle="-", lw=0.6, color="black"))
            bottom += share

    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_subtitles, fontsize=11, fontweight="bold")
    ax.set_xlim(-0.7, n_cols - 1 + 0.7)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Share of failures (%)", fontsize=11)
    ax.set_title(title, fontsize=12, pad=title_pad)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    # Legend on right, grouped by top-level
    legend_handles = []
    last_group = None
    for leaf in LEAF_ORDER:
        if leaf not in leaves_present:
            continue
        group = LEAF_GROUP[leaf]
        if group != last_group:
            legend_handles.append(mpatches.Patch(color="none",
                                                 label=f"$\\bf{{{group}}}$"))
            last_group = group
        legend_handles.append(mpatches.Patch(facecolor=GROUP_COLORS[group],
                                              edgecolor="black",
                                              hatch=LEAF_HATCH.get(leaf, ""),
                                              label=f"  {leaf}"))

    absent = [l for l in LEAF_ORDER if l not in leaves_present and l in LEAF_GROUP]
    if absent:
        legend_handles.append(mpatches.Patch(color="none", label=""))
        legend_handles.append(mpatches.Patch(color="none",
                                              label="$\\it{0\\%\\ in\\ all:}$"))
        for l in absent:
            legend_handles.append(mpatches.Patch(color="none",
                                                  label=f"  $\\it{{{l}}}$"))

    ax.legend(handles=legend_handles, loc="center left",
              bbox_to_anchor=(1.02, 0.5), fontsize=9,
              frameon=True, handlelength=2.0)

    if extra_footer:
        fig.text(0.5, 0.01, extra_footer, ha="center", fontsize=9, style="italic")

    fig.tight_layout()
    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=180, bbox_inches="tight")
    print(f"saved → {out_pdf.name}, {out_png.name}")
