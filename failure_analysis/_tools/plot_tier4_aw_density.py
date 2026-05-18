#!/usr/bin/env python3
"""Density plot of nearest-neighbor cosine similarity to AndroidWorld
instructions, comparing two distributions:

  - Tier-4 (45 tasks): each task's max similarity to any of 116 AW tasks.
    The distribution we want readers to see clusters at low values.
  - AndroidWorld self-control (116 tasks, excl. 11 near-identical
    Verify-variant pairs that score >= 0.99): each task's max similarity
    to any *other* AW task. The within-suite reference.

Output:
  docs/final/cli_advantage/figures/tier4_aw_similarity_density.png
"""
import json
import hashlib
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde

ROOT = Path('/home/ligu/projects/SkyRL-AndriodWorld')
TOOLS = ROOT / 'failure_analysis/_tools'
CACHE = TOOLS / '.cache'
OUT = ROOT / 'docs/final/cli_advantage/figures'
OUT.mkdir(parents=True, exist_ok=True)

SEEDS = (7, 30, 1234)


def cache_key(t: str) -> str:
    return hashlib.sha256(t.encode('utf-8')).hexdigest()


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.clip(n, 1e-12, None)


def main():
    emb = json.loads((CACHE / 'embeddings.json').read_text())
    aw = json.loads((CACHE / 'aw_goals.json').read_text())['tasks']

    # AW stack (n_aw, S, D)
    A_rows, aw_names = [], []
    for t in aw:
        A_rows.append([emb[cache_key(t['seeds'][str(s)])] for s in SEEDS])
        aw_names.append(t['name'])
    A = normalize(np.asarray(A_rows, dtype=np.float32))

    # T4: load goals from the 3 seed JSONLs
    t4_goals = {}
    for s in SEEDS:
        for line in (ROOT / f'eval-runners/data/tier4/realistic_subset_seed{s}.jsonl').read_text().splitlines():
            if not line.strip(): continue
            d = json.loads(line); t4_goals.setdefault(int(d['task_id']), {})[s] = d['task']
    T_rows = []
    for tid in sorted(t4_goals):
        T_rows.append([emb[cache_key(t4_goals[tid][s])] for s in SEEDS])
    T = normalize(np.asarray(T_rows, dtype=np.float32))

    # Per-seed cosine then average
    sim_t4_aw = np.einsum('isd,jsd->sij', T, A).mean(axis=0)  # (n_t4, n_aw)
    sim_aw_aw = np.einsum('isd,jsd->sij', A, A).mean(axis=0)  # (n_aw, n_aw)
    np.fill_diagonal(sim_aw_aw, -np.inf)

    # NN distributions
    nn_t4 = sim_t4_aw.max(axis=1)                              # n=45
    nn_aw_full = sim_aw_aw.max(axis=1)                         # n=116 (raw)
    sim_aw_clean = sim_aw_aw.copy()
    sim_aw_clean[sim_aw_aw >= 0.95] = -np.inf                  # drop Verify dupes
    nn_aw = sim_aw_clean.max(axis=1)                           # n=116 (clean)

    # Plot
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=140)

    xs = np.linspace(0.0, 1.0, 400)
    kde_aw = gaussian_kde(nn_aw, bw_method=0.20)
    kde_t4 = gaussian_kde(nn_t4, bw_method=0.20)
    ax.fill_between(xs, kde_aw(xs), alpha=0.30, color='#cc6677',
                    label=f'AndroidWorld → AndroidWorld  (n={len(nn_aw)})')
    ax.plot(xs, kde_aw(xs), color='#cc6677', linewidth=2.0)
    ax.fill_between(xs, kde_t4(xs), alpha=0.30, color='#3366aa',
                    label=f'Tier-4 → AndroidWorld  (n={len(nn_t4)})')
    ax.plot(xs, kde_t4(xs), color='#3366aa', linewidth=2.0)

    # Headline annotations
    ax.axvline(0.70, color='gray', linestyle='--', linewidth=1, alpha=0.6)
    ax.text(0.70, ax.get_ylim()[1] * 0.95, '  0.70', fontsize=9,
            color='gray', va='top')

    ax.set_xlabel('similarity to AndroidWorld instructions', fontsize=11)
    ax.set_ylabel('density', fontsize=11)
    ax.set_title('Semantic similarity between Tier-4 and AndroidWorld instructions',
                 fontsize=12, pad=10)
    ax.set_xlim(0.0, 1.0)
    ax.grid(True, alpha=0.25)
    ax.legend(loc='upper left', frameon=False, fontsize=10)

    # Inline stat box (top-right)
    stat_text = (
        f'Tier-4 → AW:   mean {nn_t4.mean():.2f}, max {nn_t4.max():.2f}\n'
        f'                {(nn_t4 >= 0.70).sum()}/45 ≥ 0.70 ({(nn_t4 >= 0.70).sum() / 45 * 100:.0f}%)\n'
        f'                {(nn_t4 >= 0.65).sum()}/45 ≥ 0.65 ({(nn_t4 >= 0.65).sum() / 45 * 100:.0f}%)\n\n'
        f'AW → AW:       mean {nn_aw.mean():.2f}, max {nn_aw.max():.2f}\n'
        f'                {(nn_aw >= 0.70).sum()}/116 ≥ 0.70 ({(nn_aw >= 0.70).sum() / 116 * 100:.0f}%)\n'
        f'                {(nn_aw >= 0.65).sum()}/116 ≥ 0.65 ({(nn_aw >= 0.65).sum() / 116 * 100:.0f}%)'
    )
    ax.text(0.98, 0.95, stat_text, transform=ax.transAxes,
            fontsize=8.5, family='monospace', va='top', ha='right',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                      edgecolor='lightgray', alpha=0.9))

    fig.tight_layout()
    out_png = OUT / 'tier4_aw_similarity_density.png'
    fig.savefig(out_png, bbox_inches='tight')
    print(f'wrote {out_png}')

    # Also save a PDF for paper use
    out_pdf = OUT / 'tier4_aw_similarity_density.pdf'
    fig.savefig(out_pdf, bbox_inches='tight')
    print(f'wrote {out_pdf}')


if __name__ == '__main__':
    main()
