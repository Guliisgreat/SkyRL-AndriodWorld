# fig2 — Variant Effect (TB-leaf level): Codex bash_only vs bash_tool

**Paper placement:** **Main paper.**
**Figure file:** `fig2_variant_effect_leaf.pdf` / `.png`
**Raw data:** `fig2_variant_effect_leaf.csv`
**Source script:** `docent_analyses/figures/figure7_bash_only_vs_bash_tool.py`
**Companion (appendix):** `figA2_variant_effect_clusters.{pdf,csv,md}` — same
finding decomposed into Disobey-Specification sub-clusters.

---

## Caption (paper-ready)

**Figure 2. Effect of the bash-tool wrapper on GPT-5.3 Codex's failure
profile (TB-leaf level).** Two variant groups (bash\_only: raw shell
strings emitted by the agent; bash\_tool: structured JSON tool calls
unwrapped by the harness), each showing the prevalence of the four active
TB leaves. Both pools are restricted to GPT-5.3 Codex trajectories on the
fair-comparison subset (273 bash\_only failures, 184 bash\_tool
failures; 13 GUI-only AndroidWorld tasks excluded). Bars are TB-leaf
prevalence — a trajectory contributes to a bar if its primary or any
secondary cluster maps to that leaf. The five TB leaves not shown (Step
Repetition, Unaware of Termination, Context Loss, Task Derailment, No or
Incorrect Verification) were 0\% in both variants.

**Headline reading:** the tool wrapper halves Codex's Premature
Termination (−14 pp) but raises
Reasoning-Action Mismatch (+12 pp) and
Weak Verification (+9 pp) by a similar
combined amount. Disobey Specification stays essentially flat
(82\% → 80\%). The
wrapper does not reduce overall failure load; it *converts* one kind of
failure (cheap-exit) into another (tried-but-still-wrong). The mechanism
is unpacked at the sub-cluster level in Appendix Figure A2.

---

## Headline findings

1. **Premature Termination halves.** 26% →
   12%
   (Δ = −14 pp). The
   wrapper's structured-action contract makes it harder for Codex to call
   `finish` while the verifier has no readable state.

2. **Reasoning-Action Mismatch grows by ~12 pp.**
   19% → 32%. Trajectories
   that previously *quit* (PT) now *try* — but the tries are still wrong
   ("uncertainty-then-commit" guessed enums, dispatch-as-state-change).

3. **Weak Verification grows by ~9 pp.**
   50% → 59%. The wrapper
   also induces more "verify by re-reading the same surface I just wrote
   to" patterns — formal verification that doesn't cross-check.

4. **Disobey Specification is variant-invariant.**
   82% → 80%
   (Δ = -3 pp). The dominant
   failure mode does not budge — *what* Codex tries to do is set by the
   model; the wrapper only shapes *whether and how* it follows through.

5. **The PT shift is real reorganization, not absorption.** The
   ≈14 pp of PT-mass lost reappears as +12 pp RAM + +9 pp WV — i.e., the
   trajectories that used to quit early are now staying alive and
   migrating into other failure modes (this redistribution is mechanically
   explained at the cluster level in Figure A2).

---

## Raw values (also in `fig2_variant_effect_leaf.csv`)

| TB leaf | bash\_only (n=273) | bash\_tool (n=184) | Δ pp |
|---|---:|---:|---:|
| **Disobey Specification** | 82% | 80% | -3 |
| **Reasoning-Action Mismatch** | 19% | 32% | +12 |
| **Premature Termination** | 26% | 12% | -14 |
| **Weak Verification** | 50% | 59% | +9 |

(All other TB leaves are 0% in both variants.)
