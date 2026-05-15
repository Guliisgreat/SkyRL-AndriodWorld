# Multi-Label Rubric Heuristic View — All 126 Failures

> Each trajectory is annotated with the **set of all rubric leaves** whose
> heuristic detectors fire (multi-label). Drops the single-label priority
> assignment used in `rubric_summary.md`.

**Pool:** 126 failures from `pilot_set.jsonl`

## How many leaves fire per trajectory?

| # Leaves matched | Count | % |
|---:|---:|---:|
| 0 | 52 | 41% |
| 1 | 46 | 37% |
| 2 | 22 | 17% |
| 3 | 5 | 4% |
| 4 | 1 | 1% |

## Per-leaf prevalence (multi-label)

Each row independent: how often does that leaf fire? Sums >100% because
a single trajectory can match multiple leaves.

| TB leaf | Trajectories matched | % |
|---|---:|---:|
| disobey specification | 13 | 10% |
| step repetition | 22 | 17% |
| unaware of termination conditions | 11 | 9% |
| context loss | 25 | 20% |
| task derailment | 0 | 0% |
| reasoning action mismatch | 9 | 7% |
| premature termination | 5 | 4% |
| no or incorrect verification | 3 | 2% |
| weak verification | 21 | 17% |

## Per-agent multi-label leaf prevalence

Cell = % of that agent's failures where the leaf fires (independent).

| Agent | n | disobey specification | step repetition | unaware of termination conditions | context loss | task derailment | reasoning action mismatch | premature termination | no or incorrect verification | weak verification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ClaudeCodeCLI | 31 | 10% | 39% | 13% | 29% | 0% | 0% | 0% | 0% | 16% |
| MiniSweAgent | 59 | 7% | 3% | 5% | 12% | 0% | 15% | 8% | 5% | 5% |
| Terminus2 | 36 | 17% | 22% | 11% | 25% | 0% | 0% | 0% | 0% | 36% |

## Top co-occurrence pairs

Of trajectories matching ≥ 2 leaves, which leaf pairs appear together most?

| Leaf A | Leaf B | Count |
|---|---|---:|
| context loss | step repetition | 7 |
| step repetition | weak verification | 5 |
| step repetition | unaware of termination conditions | 5 |
| context loss | weak verification | 4 |
| disobey specification | weak verification | 4 |
| unaware of termination conditions | weak verification | 3 |
| context loss | disobey specification | 2 |
| disobey specification | unaware of termination conditions | 2 |
| disobey specification | step repetition | 2 |
| disobey specification | reasoning action mismatch | 2 |
| no or incorrect verification | reasoning action mismatch | 1 |
| context loss | premature termination | 1 |
| disobey specification | premature termination | 1 |
| premature termination | reasoning action mismatch | 1 |
| reasoning action mismatch | step repetition | 1 |

## Heuristic blind-spots

- **52 / 126 trajectories (41%) match no leaf at all.**
  These are heuristic-blind: they failed for reasons no current detector catches.
  Per-agent:
  - ClaudeCodeCLI: 8/31 (26%) heuristic-blind
  - MiniSweAgent: 32/59 (54%) heuristic-blind
  - Terminus2: 12/36 (33%) heuristic-blind

These need the LLM judge to be classified.