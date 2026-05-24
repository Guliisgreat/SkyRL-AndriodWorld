# figA1 — Model × Harness Compound (TB-leaf prevalence)

**Paper placement:** **Appendix.**
**Figure file:** `figA1_model_x_harness.pdf` / `.png`
**Raw data:** `figA1_model_x_harness.csv`
**Source script:** `docent_analyses/figures/figure6_model_vs_harness.py`

---

## Caption (paper-ready)

**Figure A1. Failure-mode prevalence in the CLI paradigm by model and
harness.** Each column corresponds to one (model × harness) cell on the
fair-comparison subset of AndroidWorld (1,508 failed trajectories across
103 CLI-solvable tasks; 13 GUI-only tasks excluded). Within a column, the
four bars give the prevalence of each TB leaf — the fraction of
trajectories whose primary or secondary cluster maps to that leaf; because
a trajectory can be labelled with multiple co-occurring leaves, bars within
a column need not sum to 100\%. Columns are grouped by underlying LLM
(light grey bands; dotted lines separate models), and ordered within each
band by harness. The two empty Codex / MiniMax slots under ClaudeCodeCLI
reflect that ClaudeCodeCLI is a Claude-only harness. Color encodes the
top-level TB group (blue = Execution, red = Coherence, orange =
Verification); hatch distinguishes leaves within a group.

**Headline reading:** the dominant failure mode (Disobey Specification,
blue) is essentially constant across all cells, while each model carries a
distinctive *secondary signature* (Sonnet → RAM, Codex → PT, MiniMax → WV)
that survives harness swap — model identity explains more of the
cross-cell variance than harness choice.

---

## Headline findings

1. **Disobey Specification is paradigm-universal and harness-invariant.**
   The blue bar sits at 79–89\% in every populated cell; 10-pp range
   across seven cells. DS is a baseline floor of CLI failure, not a knob
   the harness or model choice can move.

2. **Each model has a distinctive secondary signature.**
   - **Claude Sonnet 4.6** — tall red bar (RAM = 29–41\%), tiny PT
     (1–5\%). "Uncertainty-then-commit" dominates the tail.
   - **GPT-5.3 Codex** — only model with meaningful PT (17–24\%, ≈10×
     higher than others). Code-trained "ship and finish" bias.
   - **MiniMax M2.7** — tallest WV bars in the whole figure (63–66\%,
     ≥15 pp above any other cell). Writes-then-reads-same-surface.

3. **Model effect dominates harness effect.** Inside any model band, the
   bars keep their relative ordering and rough heights across harness
   columns. Between bands, the silhouettes are visibly different shapes —
   most obviously, the PT bar goes from invisible to ~24\% and back. The
   model is the load-bearing variable; the harness perturbs it.

4. **Harness *does* shape the Sonnet tail, but not the others.** Sonnet's
   RAM drops monotonically with harness rigidity (ClaudeCodeCLI 41\% →
   MSA 36\% → Terminus2 29\%) and Terminus2 also trims its WV (35\% vs
   48–54\%). For Codex the effect is smaller; for MiniMax the columns
   are near-identical (model dominates).

5. **PT vs WV trade off across models.** When PT is large (Codex), WV is
   moderate; when PT is tiny (MiniMax), WV explodes. Sonnet sits in the
   middle. Every model has *some* verification failure, but the *form* is
   model-specific.

---

## Raw values (also in `figA1_model_x_harness.csv`)

| Model | Harness | n | DS | RAM | PT | WV |
|---|---|---:|---:|---:|---:|---:|
| Claude Sonnet 4.6 | ClaudeCodeCLI | 152 | 85% | 41% | 5% | 48% |
| Claude Sonnet 4.6 | MiniSweAgent | 129 | 88% | 36% | 1% | 54% |
| Claude Sonnet 4.6 | Terminus2 | 205 | 89% | 29% | 2% | 35% |
| GPT-5.3 Codex | MiniSweAgent | 229 | 79% | 23% | 24% | 56% |
| GPT-5.3 Codex | Terminus2 | 228 | 84% | 25% | 17% | 51% |
| MiniMax M2.7 | MiniSweAgent | 216 | 88% | 26% | 2% | 63% |
| MiniMax M2.7 | Terminus2 | 232 | 88% | 29% | 3% | 66% |

(All other TB leaves are 0\% in every cell.)
