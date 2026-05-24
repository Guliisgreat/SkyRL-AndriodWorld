#!/usr/bin/env python3
"""Figure 3 — Cross-paradigm failure-mode comparison: CLI vs GUI.

Vertical stacked bars at TB-LEAF level. Shared rendering with Figs 1 & 2.

Data sources:
  - CLI: 2,040 per-trajectory labels (Sonnet 4.6, MSA + Terminus2 + ClaudeCodeCLI)
  - GUI: 245 per-trajectory labels (Opus 4.7, full pool)
"""
from __future__ import annotations
import csv
from pathlib import Path

from _render_lib import (
    load_cluster_to_leaf, load_labels, leaf_distribution,
    render_stacked_bars, LEAF_ORDER,
    filter_to_cli_solvable, GUI_ONLY_TASK_IDS,
)

ROOT = Path(__file__).resolve().parent
WS_CLI = ROOT.parent / "2026-05-21_android-cli-failures-combined"
WS_GUI = ROOT.parent / "2026-05-22_android-gui-failures"
CLI_LABELS = WS_CLI / "classification/cluster_labels_full.jsonl"
CLI_MAP    = WS_CLI / "consensus_mapping_v3.json"
GUI_LABELS = WS_GUI / "classification/cluster_labels.jsonl"
GUI_MAP    = WS_GUI / "consensus_mapping_gui.json"


def main():
    cli_c2l = load_cluster_to_leaf(CLI_MAP)
    gui_c2l = load_cluster_to_leaf(GUI_MAP)
    cli_rows_all = load_labels(CLI_LABELS)
    gui_rows_all = load_labels(GUI_LABELS)
    # Fair-comparison filter: restrict both pools to CLI-solvable tasks
    # (drop the 13 GUI-only tasks per AndroidWorld ground-truth reference)
    cli_rows = filter_to_cli_solvable(cli_rows_all)
    gui_rows = filter_to_cli_solvable(gui_rows_all)
    cli_n, cli_dist = leaf_distribution(cli_rows, cli_c2l)
    gui_n, gui_dist = leaf_distribution(gui_rows, gui_c2l)

    print(f"CLI: {cli_n} failures (filtered from {len(cli_rows_all)} — dropped {len(cli_rows_all)-cli_n} on GUI-only tasks)")
    print(f"GUI: {gui_n} failures (filtered from {len(gui_rows_all)} — dropped {len(gui_rows_all)-gui_n} on GUI-only tasks)")
    print(f"GUI-only task IDs filtered: {sorted(GUI_ONLY_TASK_IDS)}\n")
    for label, dist in [("CLI", cli_dist), ("GUI", gui_dist)]:
        print(f"{label}:")
        for leaf in LEAF_ORDER:
            if leaf in dist:
                print(f"  {leaf:35} {dist[leaf]:>5.1f}%")
        print()

    render_stacked_bars(
        columns=[
            ("CLI", cli_n, cli_dist),
            ("GUI", gui_n, gui_dist),
        ],
        title=("Figure 3 — Cross-paradigm failure-mode distribution\n"
               "CLI vs GUI agents on the 103 CLI-solvable AndroidWorld tasks "
               "(13 GUI-only tasks excluded)"),
        x_subtitles=[
            f"CLI\n({cli_n:,} failures, Sonnet 4.6)",
            f"GUI\n({gui_n} failures, Opus 4.7)",
        ],
        out_pdf=ROOT / "figure3_cli_vs_gui.pdf",
        out_png=ROOT / "figure3_cli_vs_gui.png",
        figsize=(11, 9),
        extra_footer=(f"GUI-only tasks excluded (13/116 per AndroidWorld ground-truth): "
                      f"CLI dropped {len(cli_rows_all)-cli_n} of {len(cli_rows_all)}; "
                      f"GUI dropped {len(gui_rows_all)-gui_n} of {len(gui_rows_all)}."),
    )

    with (ROOT / "figure3_data.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["paradigm", "n_failures", "tb_leaf", "share_pct"])
        for label, n, dist in [("CLI", cli_n, cli_dist), ("GUI", gui_n, gui_dist)]:
            for leaf in LEAF_ORDER:
                w.writerow([label, n, leaf, f"{dist.get(leaf, 0):.2f}"])
    print(f"wrote → figure3_data.csv")


if __name__ == "__main__":
    main()
