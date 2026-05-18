#!/usr/bin/env python3
"""Paradigm-gap bar chart: per-category success rate of CLI vs GUI agents
on the 45-task Tier-4 realistic subset, averaged across seeds {7, 30, 1234}.

Each (category, paradigm) cell is the mean SR over its 3 agents × 3 seeds.
Individual agent points are overlaid for transparency.

Output:
  docs/final/cli_advantage/figures/tier4_paradigm_gap.{png,pdf}
"""
import json
import sys
from pathlib import Path
import statistics as stats

import numpy as np
import matplotlib.pyplot as plt

ROOT = Path('/home/ligu/projects/SkyRL-AndriodWorld')
OUT = ROOT / 'docs/final/cli_advantage/figures'
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / 'docker/androidworld_2026plusswipe_tier4'))
from test_integration import GOLDEN_PATHS
CAT_BY_ID = {gp.task_id: gp.category for gp in GOLDEN_PATHS}

# 3 seeds × 3 CLI + 3 GUI agents from the eval doc's source-data table
AGENTS = {
    # CLI agents
    'Claude CLI (Opus 4.7)': {
        'paradigm': 'CLI',
        'runs': {
            7:    'eval-runners/results/ClaudeCodeCLI_claudeopus47_260515_2212/results.jsonl',
            30:   'eval-runners/results/ClaudeCodeCLI_claudeopus47_260517_0217/results.jsonl',
            1234: 'eval-runners/results/ClaudeCodeCLI_claudeopus47_260517_0236/results.jsonl',
        },
    },
    'mini-swe + m2.7': {
        'paradigm': 'CLI',
        'runs': {
            7:    'eval-runners/results/MiniSweAgent_openrouterminimaxminimaxm27_260517_1341/results.jsonl',
            30:   'eval-runners/results/MiniSweAgent_openrouterminimaxminimaxm27_260517_2028/results.jsonl',
            1234: 'eval-runners/results/MiniSweAgent_openrouterminimaxminimaxm27_260517_2036/results.jsonl',
        },
    },
    'Terminus2 + codex': {
        'paradigm': 'CLI',
        'runs': {
            7:    'eval-runners/results/Terminus2_openaigpt53codex_260517_1454/results.jsonl',
            30:   'eval-runners/results/Terminus2_openaigpt53codex_260517_1527/results.jsonl',
            1234: 'eval-runners/results/Terminus2_openaigpt53codex_260517_1540/results.jsonl',
        },
    },
    # GUI agents
    'GUI-Owl-1.5-32B': {
        'paradigm': 'GUI',
        'runs': {
            7:    'eval-runners/results/ClaudeCodeCLI_sharedmodelsGUIOwl1532BInstruct_260517_2031/results.jsonl',
            30:   'eval-runners/results/ClaudeCodeCLI_sharedmodelsGUIOwl1532BInstruct_260517_2118/results.jsonl',
            1234: 'eval-runners/results/ClaudeCodeCLI_sharedmodelsGUIOwl1532BInstruct_260517_2159/results.jsonl',
        },
    },
    'MAI-UI-8B': {
        'paradigm': 'GUI',
        'runs': {
            7:    'eval-runners/results/ClaudeCodeCLI_sharedmodelsMAIUI8B_260517_0358/results.jsonl',
            30:   'eval-runners/results/ClaudeCodeCLI_sharedmodelsMAIUI8B_260517_0425/results.jsonl',
            1234: 'eval-runners/results/ClaudeCodeCLI_sharedmodelsMAIUI8B_260517_0451/results.jsonl',
        },
    },
    'Qwen3-VL-32B': {
        'paradigm': 'GUI',
        'runs': {
            7:    'eval-runners/results/ClaudeCodeCLI_qwenqwen3vl32binstruct_260517_0303/results.jsonl',
            30:   'eval-runners/results/ClaudeCodeCLI_qwenqwen3vl32binstruct_260517_0325/results.jsonl',
            1234: 'eval-runners/results/ClaudeCodeCLI_qwenqwen3vl32binstruct_260517_0338/results.jsonl',
        },
    },
}

CAT_ORDER = ['B', 'C', 'A', 'D', 'E']
CAT_LABEL = {
    'B': 'Bulk /\nDedup',
    'C': 'Filter /\nCoverage',
    'A': 'Aggregation /\nTopK',
    'D': 'CrossApp',
    'E': 'Hidden\nState',
}


def category_sr(rows_by_seed, cat):
    """Mean SR across seeds for a given category, plus per-seed list."""
    per_seed = []
    for seed, rows in rows_by_seed.items():
        in_cat = [r for r in rows if CAT_BY_ID.get(int(r['task_id'])) == cat]
        if not in_cat:
            continue
        per_seed.append(sum(1 for r in in_cat if r.get('reward', 0) == 1) / len(in_cat))
    return stats.mean(per_seed), per_seed


def overall_sr(rows_by_seed):
    per_seed = []
    for seed, rows in rows_by_seed.items():
        per_seed.append(sum(1 for r in rows if r.get('reward', 0) == 1) / len(rows))
    return stats.mean(per_seed), per_seed


def load(path):
    return [json.loads(l) for l in open(ROOT / path) if l.strip()]


def main():
    # Load all agent results
    for name, info in AGENTS.items():
        info['rows_by_seed'] = {s: load(p) for s, p in info['runs'].items()}

    # Compute per-(agent, category) mean + per-seed list
    grid = {}  # grid[agent][cat] = (mean, per_seed_list)
    for name, info in AGENTS.items():
        grid[name] = {}
        for cat in CAT_ORDER:
            grid[name][cat] = category_sr(info['rows_by_seed'], cat)
        grid[name]['ALL'] = overall_sr(info['rows_by_seed'])

    # Group means per paradigm
    paradigms = {
        'CLI': [n for n, i in AGENTS.items() if i['paradigm'] == 'CLI'],
        'GUI': [n for n, i in AGENTS.items() if i['paradigm'] == 'GUI'],
    }

    # Plot
    fig, ax = plt.subplots(figsize=(9.0, 4.6), dpi=140)

    cats_plus = CAT_ORDER + ['ALL']
    x = np.arange(len(cats_plus))
    width = 0.36

    cli_color = '#2c5aa0'
    gui_color = '#c44e4e'

    cli_means = []
    gui_means = []
    cli_indiv_pts = []  # list of (xpos, value) for individual CLI agents
    gui_indiv_pts = []
    for ix, cat in enumerate(cats_plus):
        cli_vals = [grid[n][cat][0] * 100 for n in paradigms['CLI']]
        gui_vals = [grid[n][cat][0] * 100 for n in paradigms['GUI']]
        cli_means.append(np.mean(cli_vals))
        gui_means.append(np.mean(gui_vals))
        for v in cli_vals:
            cli_indiv_pts.append((ix - width/2, v))
        for v in gui_vals:
            gui_indiv_pts.append((ix + width/2, v))

    bars_cli = ax.bar(x - width/2, cli_means, width,
                      color=cli_color, alpha=0.85,
                      edgecolor='white', linewidth=1.0,
                      label='CLI agents (n=3)')
    bars_gui = ax.bar(x + width/2, gui_means, width,
                      color=gui_color, alpha=0.85,
                      edgecolor='white', linewidth=1.0,
                      label='GUI agents (n=3)')

    # Individual agent dots overlaid (transparency for spread)
    cli_xs, cli_ys = zip(*cli_indiv_pts)
    gui_xs, gui_ys = zip(*gui_indiv_pts)
    # Add a small jitter
    rng = np.random.default_rng(42)
    cli_xs_j = np.array(cli_xs) + rng.uniform(-0.06, 0.06, size=len(cli_xs))
    gui_xs_j = np.array(gui_xs) + rng.uniform(-0.06, 0.06, size=len(gui_xs))
    ax.scatter(cli_xs_j, cli_ys, c='white', edgecolors='#0c2a55',
               s=22, linewidth=0.9, zorder=5)
    ax.scatter(gui_xs_j, gui_ys, c='white', edgecolors='#6b1717',
               s=22, linewidth=0.9, zorder=5)

    # Bar value labels
    for ix, (cli_v, gui_v) in enumerate(zip(cli_means, gui_means)):
        ax.text(ix - width/2, cli_v + 1.5, f'{cli_v:.0f}',
                ha='center', va='bottom', fontsize=9, color=cli_color, fontweight='bold')
        ax.text(ix + width/2, gui_v + 1.5, f'{gui_v:.0f}',
                ha='center', va='bottom', fontsize=9, color=gui_color, fontweight='bold')
        # Gap annotation above
        gap = cli_v - gui_v
        ymax = max(cli_v, gui_v) + 9
        ax.annotate('', xy=(ix - width/2, ymax - 3), xytext=(ix + width/2, ymax - 3),
                    arrowprops=dict(arrowstyle='<->', color='gray', lw=0.8))
        ax.text(ix, ymax, f'+{gap:.0f} pp', ha='center', va='bottom',
                fontsize=8.5, color='gray', style='italic')

    ax.set_xticks(x)
    ax.set_xticklabels([CAT_LABEL.get(c, c) for c in cats_plus], fontsize=10)
    ax.set_ylabel('Success rate (%, mean across 3 seeds)', fontsize=10)
    ax.set_title('Tier-4 success rate by category — CLI vs GUI paradigm gap',
                 fontsize=12, pad=12)
    ax.set_ylim(0, 110)
    ax.set_yticks(range(0, 101, 20))
    ax.grid(axis='y', alpha=0.25)
    ax.legend(loc='upper right', frameon=False, fontsize=9.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    fig.tight_layout()
    for ext in ('png', 'pdf'):
        out = OUT / f'tier4_paradigm_gap.{ext}'
        fig.savefig(out, bbox_inches='tight')
        print(f'wrote {out}')


if __name__ == '__main__':
    main()
