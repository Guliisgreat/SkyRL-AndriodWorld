#!/usr/bin/env python3
"""
Analyze raw_timings.csv and produce:
  1. summary_stats.csv   — per-condition mean, std, median, 95% CI
  2. bar chart (PNG+PDF) — grouped by category with error bars
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

# Resolve project paths
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", ".."))

from experiments.exp1_observation_overhead.config import OUTPUT_DIR


def load_data(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    required = {"condition", "category", "screen", "rep", "wall_clock_s", "success"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise ValueError(f"Missing columns in CSV: {missing}")
    return df


def compute_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-condition summary stats (only successful runs)."""
    df_ok = df[df["success"] == True].copy()  # noqa: E712
    rows = []
    for (cond, cat), grp in df_ok.groupby(["condition", "category"]):
        vals = grp["wall_clock_s"].values
        n = len(vals)
        mean = np.mean(vals)
        std = np.std(vals, ddof=1) if n > 1 else 0.0
        median = np.median(vals)
        ci95 = 1.96 * std / np.sqrt(n) if n > 1 else 0.0
        rows.append(
            {
                "condition": cond,
                "category": cat,
                "n": n,
                "mean_s": round(mean, 4),
                "std_s": round(std, 4),
                "median_s": round(median, 4),
                "ci95_s": round(ci95, 4),
                "min_s": round(np.min(vals), 4),
                "max_s": round(np.max(vals), 4),
            }
        )
    return pd.DataFrame(rows)


def plot_chart(summary: pd.DataFrame, output_dir: str):
    """Grouped bar chart: categories on x-axis, conditions as bars."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("WARNING: matplotlib not installed — skipping chart generation.")
        return

    # Category ordering
    cat_order = ["Screenshot", "Screenshot (breakdown)", "A11y Tree", "gRPC Forwarder", "Direct ADB"]
    colors = {
        "Screenshot": "#4C72B0",
        "Screenshot (breakdown)": "#7BA7D7",
        "A11y Tree": "#55A868",
        "gRPC Forwarder": "#2D8E4E",
        "Direct ADB": "#C44E52",
    }

    fig, ax = plt.subplots(figsize=(14, 5))

    # Within each category, plot individual conditions side-by-side
    x_ticks = []
    x_labels = []
    pos = 0
    bar_width = 0.6
    gap_within = 0.15
    gap_between = 1.0

    for cat in cat_order:
        cat_df = summary[summary["category"] == cat].sort_values("mean_s")
        if cat_df.empty:
            continue
        for _, row in cat_df.iterrows():
            ax.bar(
                pos,
                row["mean_s"],
                width=bar_width,
                color=colors.get(cat, "#999999"),
                edgecolor="white",
                yerr=row["ci95_s"],
                capsize=4,
                error_kw={"elinewidth": 1.2},
            )
            x_ticks.append(pos)
            x_labels.append(row["condition"].replace("_", "\n"))
            pos += bar_width + gap_within
        pos += gap_between  # extra gap between categories

    ax.set_xticks(x_ticks)
    ax.set_xticklabels(x_labels, fontsize=8)
    ax.set_ylabel("Wall-clock time (seconds)")
    ax.set_title("Per-Step Observation Overhead (95% CI)")
    ax.grid(axis="y", alpha=0.3)

    # Legend for categories
    from matplotlib.patches import Patch

    legend_handles = [Patch(facecolor=colors[c], label=c) for c in cat_order if c in colors]
    ax.legend(handles=legend_handles, loc="upper left")

    plt.tight_layout()

    for ext in ("png", "pdf"):
        path = os.path.join(output_dir, f"observation_overhead.{ext}")
        fig.savefig(path, dpi=200)
        print(f"  Chart saved: {path}")

    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Analyze observation overhead benchmark results.")
    parser.add_argument(
        "--input",
        default=os.path.join(OUTPUT_DIR, "raw_timings.csv"),
        help="Path to raw_timings.csv",
    )
    parser.add_argument(
        "--output-dir",
        default=OUTPUT_DIR,
        help="Directory for output files",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"Loading data from {args.input} ...")
    df = load_data(args.input)
    print(f"  {len(df)} rows, {df['condition'].nunique()} conditions, {df['screen'].nunique()} screens")

    # Failure rate
    n_fail = (~df["success"]).sum()
    if n_fail > 0:
        print(f"  WARNING: {n_fail} failed measurements ({n_fail / len(df) * 100:.1f}%)")

    summary = compute_summary(df)
    summary_path = os.path.join(args.output_dir, "summary_stats.csv")
    summary.to_csv(summary_path, index=False)
    print(f"  Summary saved: {summary_path}")

    # Print table
    print("\n" + "=" * 80)
    print(f"  {'Condition':<25s} {'Category':<14s} {'n':>5s} {'Mean':>8s} {'Std':>8s} {'95%CI':>8s} {'Median':>8s}")
    print("-" * 80)
    for _, r in summary.iterrows():
        print(
            f"  {r['condition']:<25s} {r['category']:<14s} {r['n']:5d} "
            f"{r['mean_s']:8.4f} {r['std_s']:8.4f} {r['ci95_s']:8.4f} {r['median_s']:8.4f}"
        )
    print("=" * 80)

    plot_chart(summary, args.output_dir)
    print("\nDone.")


if __name__ == "__main__":
    main()
