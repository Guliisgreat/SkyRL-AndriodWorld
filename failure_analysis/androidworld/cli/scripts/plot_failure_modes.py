"""Draw the distribution of failure modes across all 6 CLI agents."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np

REPO = Path(__file__).resolve().parents[4]
results = [json.loads(l) for l in (REPO / 'failure_analysis/androidworld/cli/judge/outputs/judge_results.jsonl').read_text().splitlines()]

# Dedupe + filter to CLI-solvable
seen = set(); uniq = []
for r in results:
    if r['trajectory_id'] in seen: continue
    seen.add(r['trajectory_id']); uniq.append(r)
results = uniq

text = (REPO / 'docs/final/AndroidWorld2026/androidworld_ground_truth_reference_v2.md').read_text()
GUI = set(); cur = None
for ln in text.splitlines():
    m = re.match(r'###\s+Task\s+0?(\d+):', ln)
    if m: cur = int(m.group(1))
    elif cur is not None and re.match(r'\*\*Status:\*\*\s*GUI-only', ln): GUI.add(cur); cur = None
    elif cur is not None and ln.startswith('**Status:**'): cur = None
results = [r for r in results if r['task_id'] not in GUI]

N = len(results)
print(f'Plotting distribution over {N} CLI-solvable failures')

# Per-agent grouping
def agent_label(cfg):
    short = cfg.replace('_seed30_bash_only', '')
    short = short.replace('Terminus2_', 'Terminus2 / ').replace('MiniSweAgent_', 'MiniSweAgent / ').replace('ClaudeCodeCLI_', 'ClaudeCodeCLI / ')
    short = short.replace('claudeopus47', 'Opus 4.7')
    short = short.replace('claudesonnet46', 'Sonnet 4.6')
    short = short.replace('openaigpt53codex', 'GPT-5.3 Codex')
    short = short.replace('openrouterminimaxminimaxm27', 'Minimax M2.7')
    return short

# leaf name → display
LEAF_DISPLAY = {
    'weak_verification': 'Weak Verification',
    'disobey_specification': 'Disobey Specification',
    'step_repetition': 'Step Repetition',
    'reasoning_action_mismatch': 'Reasoning–Action Mismatch',
    'premature_termination': 'Premature Termination',
    'unaware_of_termination_conditions': 'Unaware of Termination',
    'no_or_incorrect_verification': 'No/Incorrect Verification',
    'task_derailment': 'Task Derailment',
    'context_loss': 'Context Loss',
    '_no_match_': '_no_match_',
}

# Per-leaf totals (primary)
prim = Counter(r['primary_leaf'] for r in results)
leaves_sorted = [l for l, _ in prim.most_common()]

# Build per-(leaf, agent) primary count
agent_set = sorted({r['config'] for r in results})
labels = [agent_label(c) for c in agent_set]
counts = defaultdict(lambda: defaultdict(int))
for r in results:
    counts[r['primary_leaf']][r['config']] += 1

# Color palette per agent (consistent ordering)
palette = ['#1f77b4', '#aec7e8', '#ff7f0e', '#ffbb78', '#2ca02c', '#98df8a']
agent_color = {c: palette[i % len(palette)] for i, c in enumerate(agent_set)}

# ============================================================
# Figure 1: stacked horizontal bars — failure modes by agent (primary)
# ============================================================
mpl.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
fig, ax = plt.subplots(figsize=(13, 7))

y_pos = np.arange(len(leaves_sorted))
left = np.zeros(len(leaves_sorted))
for cfg in agent_set:
    vals = np.array([counts[leaf].get(cfg, 0) for leaf in leaves_sorted])
    ax.barh(y_pos, vals, left=left, height=0.7, label=agent_label(cfg),
            color=agent_color[cfg], edgecolor='white', linewidth=0.5)
    left += vals

# Add total + % labels at end of each bar
totals = [prim[l] for l in leaves_sorted]
for i, (leaf, total) in enumerate(zip(leaves_sorted, totals)):
    pct = 100 * total / N
    ax.text(total + 1.5, i, f' {total}  ({pct:.0f}%)', va='center', fontsize=10, fontweight='bold')

ax.set_yticks(y_pos)
ax.set_yticklabels([LEAF_DISPLAY.get(l, l) for l in leaves_sorted], fontsize=11)
ax.invert_yaxis()
ax.set_xlabel(f'Number of failures (out of N={N})', fontsize=11)
ax.set_title(f'Failure-Mode Distribution Across CLI Agents (Primary Leaf)\n'
             f'N = {N} CLI-solvable readable failures, judge = Opus 4.7 max-effort, multi-label rubric',
             fontsize=12, pad=14)

# Legend
ax.legend(loc='lower right', fontsize=9, framealpha=0.95)
ax.grid(axis='x', linestyle='--', alpha=0.35)
ax.set_axisbelow(True)
ax.set_xlim(0, max(totals) * 1.18)

plt.tight_layout()
out_png = REPO / 'failure_analysis/androidworld/cli/judge/outputs/failure_modes_by_agent.png'
plt.savefig(out_png, dpi=150, bbox_inches='tight')
plt.close()
print(f'wrote {out_png.relative_to(REPO)}')

# ============================================================
# Figure 2: 100%-stacked bar — share of each agent's failures by leaf
# ============================================================
fig, ax = plt.subplots(figsize=(11, 7))

# Per-agent leaf shares
agent_leaf_pct = {}
for cfg in agent_set:
    cfg_total = sum(counts[l].get(cfg, 0) for l in leaves_sorted)
    agent_leaf_pct[cfg] = {l: 100 * counts[l].get(cfg, 0) / cfg_total if cfg_total else 0 for l in leaves_sorted}

x_pos = np.arange(len(agent_set))
bottom = np.zeros(len(agent_set))
leaf_palette = plt.cm.tab10(np.linspace(0, 1, len(leaves_sorted)))
for i, leaf in enumerate(leaves_sorted):
    vals = np.array([agent_leaf_pct[cfg][leaf] for cfg in agent_set])
    bars = ax.bar(x_pos, vals, bottom=bottom, width=0.7,
                  label=LEAF_DISPLAY.get(leaf, leaf), color=leaf_palette[i], edgecolor='white', linewidth=0.5)
    # Annotate cells > 8%
    for j, v in enumerate(vals):
        if v >= 8:
            ax.text(x_pos[j], bottom[j] + v / 2, f'{v:.0f}%', ha='center', va='center',
                    fontsize=9, color='white' if v >= 12 else 'black', fontweight='bold')
    bottom += vals

# Annotate total failure count on top
for j, cfg in enumerate(agent_set):
    n = sum(counts[l].get(cfg, 0) for l in leaves_sorted)
    ax.text(x_pos[j], 102, f'n={n}', ha='center', va='bottom', fontsize=10, fontweight='bold')

ax.set_xticks(x_pos)
ax.set_xticklabels([agent_label(c) for c in agent_set], rotation=18, ha='right', fontsize=10)
ax.set_ylabel('Share of agent\'s failures (%)', fontsize=11)
ax.set_ylim(0, 110)
ax.set_yticks([0, 20, 40, 60, 80, 100])
ax.set_title('Failure-Mode Composition Per CLI Agent (100%-stacked)', fontsize=12, pad=20)
ax.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=9, framealpha=0.95)
ax.grid(axis='y', linestyle='--', alpha=0.35)
ax.set_axisbelow(True)

plt.tight_layout()
out_png2 = REPO / 'failure_analysis/androidworld/cli/judge/outputs/failure_modes_per_agent_stacked.png'
plt.savefig(out_png2, dpi=150, bbox_inches='tight')
plt.close()
print(f'wrote {out_png2.relative_to(REPO)}')
