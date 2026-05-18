#!/usr/bin/env python3
"""Compute semantic similarity between Tier-4 45-task and AndroidWorld 116-task
instructions across seeds {7, 30, 1234} using OpenAI text-embedding-3-large.

Pipeline:
  1. Load Tier-4 goals from eval-runners/data/tier4/realistic_subset_seed{S}.jsonl
  2. Load AW goals from failure_analysis/_tools/.cache/aw_goals.json
     (produced by /tmp/dump_aw_goals.py via `docker exec`)
  3. Embed every unique goal string with text-embedding-3-large (3072 dim).
     Cache in failure_analysis/_tools/.cache/embeddings.json
  4. Per-pair seed-averaged cosine similarity:
        sim(T4_i, AW_j) = mean_{s in seeds} cos(emb(T4_i,s), emb(AW_j,s))
  5. Per-Tier-4 task: max sim over all 116 AW tasks; top-3 nearest AW tasks.
  6. Aggregate stats and per-category breakdown.

Outputs (JSON + CSV + Markdown summary):
  - failure_analysis/_tools/tier4_aw_similarity_matrix.json
  - failure_analysis/_tools/tier4_aw_similarity_summary.json
  - failure_analysis/_tools/tier4_aw_max_sim.csv
  - failure_analysis/_tools/tier4_aw_top3_nearest.csv

Requires OPENAI_API_KEY in env.
"""
import json
import hashlib
import os
import sys
import csv
import statistics
from pathlib import Path

import numpy as np
from openai import OpenAI

ROOT = Path('/home/ligu/projects/SkyRL-AndriodWorld')
TOOLS = ROOT / 'failure_analysis/_tools'
CACHE_DIR = TOOLS / '.cache'
EMB_CACHE_PATH = CACHE_DIR / 'embeddings.json'
AW_GOALS_PATH = CACHE_DIR / 'aw_goals.json'
SEEDS = (7, 30, 1234)
MODEL = 'text-embedding-3-large'

sys.path.insert(0, str(ROOT / 'docker/androidworld_2026plusswipe_tier4'))
from test_integration import GOLDEN_PATHS
T4_CAT = {gp.task_id: gp.category for gp in GOLDEN_PATHS}
T4_NAME = {gp.task_id: gp.task_name for gp in GOLDEN_PATHS}


# ---------- loading -------------------------------------------------------

def load_t4_goals() -> dict:
    """Returns {task_id: {seed: goal_text}}."""
    out = {}
    for s in SEEDS:
        path = ROOT / f'eval-runners/data/tier4/realistic_subset_seed{s}.jsonl'
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            tid = int(d['task_id'])
            out.setdefault(tid, {})[s] = d['task']
    return out


def load_aw_goals() -> dict:
    """Returns {aw_name: {seed: goal_text}}."""
    raw = json.loads(AW_GOALS_PATH.read_text())
    out = {}
    for t in raw['tasks']:
        out[t['name']] = {int(s): g for s, g in t['seeds'].items()}
    return out


# ---------- embedding -----------------------------------------------------

def cache_key(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load_cache() -> dict:
    if EMB_CACHE_PATH.exists():
        return json.loads(EMB_CACHE_PATH.read_text())
    return {}


def save_cache(cache: dict):
    EMB_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EMB_CACHE_PATH.write_text(json.dumps(cache))


def embed_all(strings: list[str]) -> dict[str, list[float]]:
    """Return {text: vector}. Caches by sha256(text). Batches of 256."""
    cache = load_cache()
    missing = [s for s in set(strings) if cache_key(s) not in cache]
    print(f'embed: {len(strings)} requested, {len(set(strings))} unique, '
          f'{len(missing)} new')
    if missing:
        client = OpenAI()
        BATCH = 256
        for i in range(0, len(missing), BATCH):
            batch = missing[i:i + BATCH]
            print(f'  api call: {i+1}-{i+len(batch)}/{len(missing)}', flush=True)
            resp = client.embeddings.create(model=MODEL, input=batch)
            for s, e in zip(batch, resp.data):
                cache[cache_key(s)] = e.embedding
        save_cache(cache)
    return {s: cache[cache_key(s)] for s in set(strings)}


# ---------- similarity ----------------------------------------------------

def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.clip(n, 1e-12, None)


def compute_seed_averaged_sim(t4: dict, aw: dict, emb: dict):
    """Returns:
       sim_matrix: np.array shape (n_t4, n_aw) = seed-averaged cosine
       t4_ids: list of (task_id) in row order
       aw_names: list of aw names in col order
    """
    t4_ids = sorted(t4.keys())
    aw_names = sorted(aw.keys())
    # Build embedding tensors: shape (n, n_seeds, dim)
    def stack(d, ids):
        rows = []
        for tid in ids:
            row = []
            for s in SEEDS:
                vec = np.asarray(emb[d[tid][s]], dtype=np.float32)
                row.append(vec)
            rows.append(row)
        return normalize(np.asarray(rows))

    T = stack(t4, t4_ids)     # (n_t4, S, D)
    A = stack(aw, aw_names)   # (n_aw, S, D)
    # Per-seed cosine: einsum
    # sim_s[i,j] = T[i,s] . A[j,s]
    sims_per_seed = np.einsum('isd,jsd->sij', T, A)  # (S, n_t4, n_aw)
    sim_avg = sims_per_seed.mean(axis=0)
    return sim_avg, sims_per_seed, t4_ids, aw_names


# ---------- main ----------------------------------------------------------

def main():
    if not os.environ.get('OPENAI_API_KEY'):
        sys.exit('OPENAI_API_KEY env var required')

    t4 = load_t4_goals()
    aw = load_aw_goals()
    print(f't4 tasks: {len(t4)}    aw tasks: {len(aw)}')

    # Collect all unique strings to embed
    all_strings = []
    for d in (t4, aw):
        for sd in d.values():
            for g in sd.values():
                all_strings.append(g)
    emb = embed_all(all_strings)

    sim_avg, sims_per_seed, t4_ids, aw_names = compute_seed_averaged_sim(t4, aw, emb)
    print(f'similarity matrix shape: {sim_avg.shape}')

    # Per-T4 stats
    per_task = []
    for i, tid in enumerate(t4_ids):
        row = sim_avg[i]
        order = np.argsort(-row)
        top3 = [(aw_names[j], float(row[j])) for j in order[:3]]
        per_task.append({
            'task_id': tid,
            'task_name': T4_NAME.get(tid, '?'),
            'category': T4_CAT.get(tid, '?'),
            'max_sim': float(row.max()),
            'mean_sim': float(row.mean()),
            'median_sim': float(np.median(row)),
            'top3_nearest_aw': top3,
        })

    # Aggregate stats
    max_sims = [p['max_sim'] for p in per_task]
    summary = {
        'n_t4_tasks': len(t4_ids),
        'n_aw_tasks': len(aw_names),
        'seeds': list(SEEDS),
        'model': MODEL,
        'metric': 'seed-averaged cosine (same-seed pairing)',
        'overall_max_sim': {
            'mean': statistics.mean(max_sims),
            'median': statistics.median(max_sims),
            'stdev': statistics.stdev(max_sims) if len(max_sims) > 1 else 0,
            'min': min(max_sims),
            'max': max(max_sims),
            'p25': float(np.percentile(max_sims, 25)),
            'p75': float(np.percentile(max_sims, 75)),
            'p90': float(np.percentile(max_sims, 90)),
        },
        'threshold_counts': {
            f'max_sim < {t:.1f}': sum(1 for s in max_sims if s < t)
            for t in (0.4, 0.5, 0.6, 0.7, 0.8)
        },
        'per_category': {},
    }
    for cat in 'BCADE':
        cat_sims = [p['max_sim'] for p in per_task if p['category'] == cat]
        summary['per_category'][cat] = {
            'n': len(cat_sims),
            'mean_max_sim': statistics.mean(cat_sims) if cat_sims else None,
            'median_max_sim': statistics.median(cat_sims) if cat_sims else None,
            'min_max_sim': min(cat_sims) if cat_sims else None,
            'max_max_sim': max(cat_sims) if cat_sims else None,
        }

    # Write outputs
    out_dir = TOOLS
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / 'tier4_aw_similarity_summary.json').write_text(
        json.dumps(summary, indent=2))

    matrix_path = out_dir / 'tier4_aw_similarity_matrix.json'
    matrix_path.write_text(json.dumps({
        't4_ids': t4_ids,
        'aw_names': aw_names,
        'matrix_seed_averaged': sim_avg.tolist(),
        'per_seed_matrices': {str(SEEDS[s]): sims_per_seed[s].tolist()
                              for s in range(len(SEEDS))},
    }))

    with (out_dir / 'tier4_aw_max_sim.csv').open('w') as f:
        w = csv.writer(f)
        w.writerow(['task_id', 'task_name', 'category', 'max_sim',
                    'mean_sim', 'median_sim', 'nearest_aw'])
        for p in sorted(per_task, key=lambda x: -x['max_sim']):
            w.writerow([p['task_id'], p['task_name'], p['category'],
                        f"{p['max_sim']:.4f}", f"{p['mean_sim']:.4f}",
                        f"{p['median_sim']:.4f}", p['top3_nearest_aw'][0][0]])

    with (out_dir / 'tier4_aw_top3_nearest.csv').open('w') as f:
        w = csv.writer(f)
        w.writerow(['task_id', 'task_name', 'category',
                    'nearest_aw_1', 'sim_1',
                    'nearest_aw_2', 'sim_2',
                    'nearest_aw_3', 'sim_3'])
        for p in sorted(per_task, key=lambda x: x['task_id']):
            row = [p['task_id'], p['task_name'], p['category']]
            for n, s in p['top3_nearest_aw']:
                row.extend([n, f'{s:.4f}'])
            w.writerow(row)

    # Print human summary
    print('\n=== SUMMARY ===')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
