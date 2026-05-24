#!/usr/bin/env python3
"""Figure 2 — bash_only vs +tools treatment effect for GPT-5.3 Codex
within mini-swe-agent.

2-column stacked bar showing TB-leaf distribution per action_variant.
Annotated with total-failure-rate comparison since shorter bars don't
visually capture absolute SR improvement.

Output:
  - figure2_codex_bash_only_vs_tool.pdf / .png
  - figure2_data.csv
"""
from __future__ import annotations
import csv
from pathlib import Path

from _render_lib import (
    load_cluster_to_leaf, load_labels, leaf_distribution,
    render_stacked_bars, LEAF_ORDER,
)

ROOT = Path(__file__).resolve().parent
WS_CLI = ROOT.parent / "2026-05-21_android-cli-failures-combined"
CLI_LABELS = WS_CLI / "classification/cluster_labels_full.jsonl"
CLI_MAP    = WS_CLI / "consensus_mapping_v3.json"

HARNESS = "MiniSweAgent"
MODEL = "openaigpt53codex"
VARIANTS = [
    ("bash_only", "bash-only"),
    ("bash_tool", "+tools"),
]

# Codex on AndroidWorld: 116 tasks × 3 seeds = 348 attempts per variant
TASKS_PER_VARIANT = 348


def main():
    c2l = load_cluster_to_leaf(CLI_MAP)
    all_rows = load_labels(CLI_LABELS)
    codex_rows = [r for r in all_rows
                  if r.get("agent_harness") == HARNESS
                  and r.get("model_api") == MODEL]
    print(f"Total CLI per-traj: {len(all_rows)}")
    print(f"MiniSweAgent + GPT-5.3 Codex: {len(codex_rows)}\n")

    columns = []
    x_subtitles = []
    sr_strs = []
    for variant, display in VARIANTS:
        rows = [r for r in codex_rows if r.get("action_variant") == variant]
        n, dist = leaf_distribution(rows, c2l)
        failure_rate = n / TASKS_PER_VARIANT * 100
        sr_strs.append(f"{display}: {n} failures / {TASKS_PER_VARIANT} attempts = {failure_rate:.1f}% failure rate")
        columns.append((display, n, dist))
        x_subtitles.append(f"{display}\n{n} failures\n({failure_rate:.1f}% failure rate)")
        print(f"{display}: {n} failures, failure rate {failure_rate:.1f}%")
        for leaf in LEAF_ORDER:
            if leaf in dist:
                print(f"  {leaf:35} {dist[leaf]:>5.1f}%")
        print()

    # Treatment-effect summary
    f_only = columns[0][1]
    f_tool = columns[1][1]
    delta_failures = f_tool - f_only
    delta_rate = (f_tool - f_only) / TASKS_PER_VARIANT * 100
    footer = (f"GPT-5.3 Codex within mini-swe-agent: tools reduced failures from {f_only} → {f_tool} "
              f"({delta_rate:+.1f} pp failure rate; ratio {f_tool/f_only:.2f}×).")

    render_stacked_bars(
        columns=columns,
        title=("Figure 2 — Treatment effect of structured tools on GPT-5.3 Codex\n"
               "within mini-swe-agent: bash-only vs +tools (TB 9-leaf taxonomy)"),
        x_subtitles=x_subtitles,
        out_pdf=ROOT / "figure2_codex_bash_only_vs_tool.pdf",
        out_png=ROOT / "figure2_codex_bash_only_vs_tool.png",
        figsize=(11, 9),
        extra_footer=footer,
    )

    with (ROOT / "figure2_data.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "n_failures", "task_attempts", "failure_rate_pct",
                    "tb_leaf", "share_of_failures_pct"])
        for variant_label, n, dist in columns:
            for leaf in LEAF_ORDER:
                w.writerow([variant_label, n, TASKS_PER_VARIANT,
                            f"{n/TASKS_PER_VARIANT*100:.2f}",
                            leaf, f"{dist.get(leaf, 0):.2f}"])
    print(f"wrote → figure2_data.csv")


if __name__ == "__main__":
    main()
