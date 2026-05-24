#!/usr/bin/env python3
"""Figure 1 — Failure-mode comparison across model APIs within mini-swe-agent.

3-column stacked bar showing TB-leaf distribution for each model API:
  - Claude Sonnet 4.6 (anthropic)
  - GPT-5.3 Codex (openai)
  - MiniMax M2.7 (openrouter)

All trajectories from agent_harness=MiniSweAgent. CLI per-trajectory
labels from `cluster_labels_msa.jsonl` (or `cluster_labels_full.jsonl`)
× consensus_mapping_v3.json.

Output:
  - figure1_model_apis_msa.pdf / .png
  - figure1_data.csv
"""
from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path

from _render_lib import (
    load_cluster_to_leaf, load_labels, leaf_distribution,
    render_stacked_bars, LEAF_ORDER, LEAF_GROUP,
)

ROOT = Path(__file__).resolve().parent
WS_CLI = ROOT.parent / "2026-05-21_android-cli-failures-combined"
CLI_LABELS = WS_CLI / "classification/cluster_labels_full.jsonl"
CLI_MAP    = WS_CLI / "consensus_mapping_v3.json"

# 3 model APIs to compare (within MiniSweAgent)
MODELS = [
    ("anthropicclaudesonnet46",     "Claude\nSonnet 4.6"),
    ("openaigpt53codex",            "GPT-5.3 Codex"),
    ("openrouterminimaxminimaxm27", "MiniMax\nM2.7"),
]
HARNESS = "MiniSweAgent"


def main():
    c2l = load_cluster_to_leaf(CLI_MAP)
    all_rows = load_labels(CLI_LABELS)
    # Filter to MiniSweAgent
    msa_rows = [r for r in all_rows if r.get("agent_harness") == HARNESS]
    print(f"Total CLI per-traj: {len(all_rows)}")
    print(f"MiniSweAgent subset: {len(msa_rows)}")

    columns = []
    x_subtitles = []
    for model_api, display in MODELS:
        rows = [r for r in msa_rows if r.get("model_api") == model_api]
        n, dist = leaf_distribution(rows, c2l)
        columns.append((display.replace("\n", " "), n, dist))
        x_subtitles.append(f"{display}\n({n} failures)")
        print(f"\n{display}: {n} failures")
        for leaf in LEAF_ORDER:
            if leaf in dist:
                print(f"  {leaf:35} {dist[leaf]:>5.1f}%")

    render_stacked_bars(
        columns=columns,
        title=("Figure 1 — Failure-mode distribution across model APIs\n"
               "within mini-swe-agent harness (Terminal-Bench 9-leaf taxonomy)"),
        x_subtitles=x_subtitles,
        out_pdf=ROOT / "figure1_model_apis_msa.pdf",
        out_png=ROOT / "figure1_model_apis_msa.png",
        figsize=(13, 9),
        extra_footer="All bars normalized within each model. Sub-leaves under each TB leaf in appendix taxonomy.md.",
    )

    # CSV underlying data
    with (ROOT / "figure1_data.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model_api", "n_failures", "tb_leaf", "share_pct"])
        for col_label, n, dist in columns:
            for leaf in LEAF_ORDER:
                w.writerow([col_label, n, leaf, f"{dist.get(leaf, 0):.2f}"])
    print(f"\nwrote → figure1_data.csv")


if __name__ == "__main__":
    main()
