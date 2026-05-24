# Figure 6A — Compound Grouped Bars: Model × Harness × TB Leaf

**Files**

- `figure6A_compound_groups.pdf` / `.png` — the figure
- `figure6_data.csv` — long-format prevalence data (7 cells × 4 leaves)
- `figure6_model_vs_harness.py` — render script

---

## Caption (paper-style)

**Figure 6A. Failure-mode prevalence in the CLI paradigm by model and harness.**
Each column corresponds to one (model × harness) cell on the fair-comparison
subset of AndroidWorld (1,508 failed trajectories across 103 CLI-solvable
tasks; 13 GUI-only tasks excluded). Within a column, the four bars give the
prevalence of each TB leaf — the fraction of trajectories whose primary or
secondary cluster maps to that leaf; because a trajectory can be labelled with
multiple co-occurring leaves, bars within a column need not sum to 100%.
Columns are grouped by underlying LLM (light grey bands; dotted lines separate
models), and ordered within each band by harness. The two empty Codex /
MiniMax slots under ClaudeCodeCLI reflect that ClaudeCodeCLI is a Claude-only
harness. Color encodes the top-level TB group (blue = Execution, red =
Coherence, orange = Verification); hatch distinguishes leaves within a group.
The five other TB leaves (Step Repetition, Unaware of Termination, Context
Loss, Task Derailment, No or Incorrect Verification) had 0% prevalence in
every cell and are omitted.

**Headline reading:** the dominant failure mode (Disobey Specification, blue)
is essentially constant across all cells, while each model carries a
distinctive *secondary signature* (Sonnet → RAM, Codex → PT, MiniMax → WV)
that survives harness swap — model identity explains more of the cross-cell
variance than harness choice.

---

## Findings

### 1. Disobey Specification is paradigm-universal

The blue bar sits at 79–89% in every populated cell. The 10-pp range across
seven (model, harness) cells is small compared with what the secondary leaves
do, so DS behaves like a baseline floor of CLI failure rather than something
a model or harness choice can move.

### 2. Each model has a distinctive secondary signature, visible at a glance

| Model | Visual signature |
|---|---|
| **Claude Sonnet 4.6** | Tall red bar (RAM = 29–41%), tiny orange-solid bar (PT = 1–5%). The "uncertainty-then-commit" pattern (guessed enums, dispatch-as-state-change) dominates the tail. |
| **GPT-5.3 Codex** | Only model with a meaningful **solid orange (PT)** bar (17–24%, ≈10× higher than the other two models). Codex tends to call `finish --status complete` while the verifier still has nothing to read. |
| **MiniMax M2.7** | Tallest hatched orange (WV) bars in the whole figure (63–66%, ≥15 pp above any other cell). MiniMax writes and then re-reads through the same surface aggressively, almost never pivoting to a cross-surface check. |

### 3. Model effect dominates harness effect

Inside any model band, the bars keep their relative ordering and rough heights
across the 2–3 harness columns (Sonnet's three columns are clearly variants
on the same silhouette; MiniMax's two are nearly indistinguishable). Between
bands, the silhouettes are visibly different shapes — most obviously, the PT
bar goes from invisible to ~24% and back. The model is the load-bearing
variable; the harness perturbs it.

### 4. Harness *does* shape the Sonnet tail, but not the others

- **Sonnet 4.6** — RAM share drops monotonically with harness rigidity
  (ClaudeCodeCLI 41% → MSA 36% → Terminus2 29%), and Terminus2 also trims
  Sonnet's WV (35% vs 48–54%). Suggests Terminus2's stricter wrapping helps a
  Claude model not commit to guesses.
- **Codex** — harness effect is smaller (PT 24 → 17%, rest within 5 pp).
- **MiniMax** — columns are essentially copies of each other (88/88 DS,
  26/29 RAM, 2/3 PT, 63/66 WV) — its profile is harness-invariant.

### 5. PT vs WV tradeoff per model

Reading across models, the two orange bars trade off: when PT is large
(Codex), WV is moderate; when PT is tiny (MiniMax), WV explodes. Sonnet sits
in the middle on both. Every model has *some* verification failure, but the
*form* of that failure is model-specific — Codex stops too early, MiniMax
verifies through the wrong channel.

### 6. A coding-trained model has the strongest "declare-done" bias

Codex is the only one whose PT prevalence is comparable to its RAM prevalence
(24% vs 23%). The other two collapse PT to near-zero and absorb that mass
into Weak Verification. Consistent with the hypothesis that fine-tuning on
coding tasks reinforces "ship and finish" behavior that, in an embodied-agent
setting, manifests as Premature Termination.

### 7. No CLI model produces Step Repetition or Coherence-group failures

Five of the nine TB leaves are at 0% in every cell. Combined with the
GUI-paradigm comparison (figure 4), this localises Step Repetition to the GUI
paradigm and Coherence drift to neither — the CLI/GUI difference is therefore
mostly a story about *which* execution-class and verification-class leaves
dominate, not about whether the agent loses track of state.

---

## Caveat

Prevalence allows multi-leaf assignment (mean 1.77 leaves per CLI
trajectory), so taller bars do not necessarily mean a *larger fraction of
distinct failures*; they mean a leaf is *more often present in the
trajectory's failure profile*. A primary-only stacked view (figure 3) gives
the orthogonal "what was the single dominant cause" reading.

---

## Raw values plotted

Fair-view prevalence (% trajectories where primary or secondary cluster maps
to that TB leaf):

| Model | Harness | n | DS | RAM | PT | WV |
|---|---|---:|---:|---:|---:|---:|
| Claude Sonnet 4.6 | ClaudeCodeCLI | 152 | 85% | 41% | 5% | 48% |
| Claude Sonnet 4.6 | MiniSweAgent | 129 | 88% | 36% | 1% | 54% |
| Claude Sonnet 4.6 | Terminus2 | 205 | 89% | 29% | 2% | 35% |
| GPT-5.3 Codex | MiniSweAgent | 229 | 79% | 23% | **24%** | 56% |
| GPT-5.3 Codex | Terminus2 | 228 | 84% | 25% | 17% | 51% |
| MiniMax M2.7 | MiniSweAgent | 216 | 88% | 26% | 2% | **63%** |
| MiniMax M2.7 | Terminus2 | 232 | 88% | 29% | 3% | **66%** |

(All figures from `figure6_data.csv`; full per-cluster mapping in
`taxonomy.md`.)
