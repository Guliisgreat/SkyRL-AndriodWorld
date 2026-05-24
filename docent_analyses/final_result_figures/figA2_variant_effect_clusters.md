# figA2 — Variant Effect (DS-cluster level): Codex bash_only vs bash_tool

**Paper placement:** **Appendix.** Companion to main-paper **Figure 2**;
unpacks the Disobey-Specification leaf into its sub-clusters and shows
where the wrapper's effect comes from.
**Figure file:** `figA2_variant_effect_clusters.pdf` / `.png`
**Raw data:** `figA2_variant_effect_clusters.csv`
**Source script:** `docent_analyses/figures/figure7_codex_composite.py`
(panel b extracted as a standalone figure)

---

## Caption (paper-ready)

**Figure A2. Disobey-Specification sub-cluster shifts under the bash-tool
wrapper (GPT-5.3 Codex).** Each row is one DS sub-cluster; bar length is
the change in cluster prevalence when moving from bash\_only (273
failures) to bash\_tool (184 failures), both restricted to GPT-5.3
Codex on the fair-comparison subset (13 GUI-only AndroidWorld tasks
excluded). Blue bars (top of chart) are clusters the wrapper shrinks
(helps); orange bars (bottom) are clusters the wrapper grows. The italic
column on the right gives the absolute prevalence pair
(bash\_only → bash\_tool) for context. The diamond marker (◇) flags
display-merged clusters (see Methods / taxonomy.md). The cluster
`agent_concluded_no_cli_pathway` is the presentation-layer rename of the
original Phase-2 label `task_required_gui_only_no_cli_pathway`; it
captures the agent's *false-impossibility conclusion* (not a task
property — every fair-view occurrence is on a CLI-solvable task).

**Headline reading:** the wrapper acts asymmetrically inside Disobey
Specification — it dampens four "cheap-exit" failure modes by a combined
−16 pp while only slightly growing failures that involve
*more aggressive engagement* with blocked or wrong-value surfaces
(+11 pp). Disobey Specification's leaf-level prevalence
stays flat (Figure 2) precisely because these two sets of clusters
partially cancel; the wrapper's real effect is to **raise Codex's
engagement floor**, not to fix the dominant failure leaf.

---

## Headline findings

1. **Four cheap-exit clusters shrink under bash_tool**
   (combined −16 pp). The wrapper makes Codex less likely
   to quit, fabricate, or take destructive shortcuts:
   - `agent_concluded_no_cli_pathway`: 10\% → 3\% (−6.3 pp) — agent gives
     up less often on tasks that *do* have a shell pathway.
   - `truncated_input_treated_as_complete`: 8\% → 4\% (−3.3 pp) — better
     handling of large/paged tool output.
   - `fabricated_artifact_instead_of_invoking_app_pipeline`: 14\% → 11\%
     (−2.9 pp) — harder to disguise hand-crafted bytes as captured.
   - `pm_clear_or_destructive_blanket_action`: 3\% → 1\% (−2.4 pp) —
     structured calls discourage `pm clear` / `rm -rf` shortcuts.

2. **The deepest cluster is variant-invariant.**
   `wrote_to_wrong_database_surface` sits at ~40\% in both variants
   (+0.8 pp). The model's "which surface should I write to" decision is
   not influenced by the action contract — it's a planning-level error.

3. **One cluster genuinely grows under bash_tool.**
   `permission_or_role_blocked_clipboard_or_sms`: 14\% → 18\%
   (+4.9 pp). Codex attempts blocked operations *more* under the wrapper
   — plausibly because the structured-output channel makes
   SecurityException-Parcel artifacts easier for the model to misread as
   "empty result" and retry.

4. **Two "engagement" clusters grow modestly** (+2–3 pp each).
   `wrong_output_value_at_correct_surface` (+2.4 pp) and
   `apk_static_analysis_loop_without_db_write` (+2.2 pp) both reflect
   Codex *staying alive longer* — reaching the right surface, then
   getting the value wrong; or running longer recon sessions.

5. **The asymmetry confirms the engagement-floor framing.** The
   wrapper does not improve Codex's correctness — DS stays flat — but it
   redirects ≈16 pp of cheap-exit mass into trajectories
   that *try harder*. Some of those tries land on a blocked surface
   (cluster #3 above); others get the right surface but the wrong value
   (#4). The net effect on the leaf-level numbers (Figure 2) is
   reorganization, not reduction.

---

## Raw values (also in `figA2_variant_effect_clusters.csv`)

| DS sub-cluster | bash\_only | bash\_tool | Δ pp |
|---|---:|---:|---:|
| `agent_concluded_no_cli_pathway` | 9.5% | 3.3% | −6.3 |
| `truncated_input_treated_as_complete` | 7.7% | 4.3% | −3.3 |
| `fabricated_artifact_instead_of_invoking_app_pipeline` | 14.3% | 11.4% | −2.9 |
| `pm_clear_or_destructive_blanket_action` | 2.9% | 0.5% | −2.4 |
| `wrapper_input_format_violation` ◇ | 3.3% | 2.2% | −1.1 |
| `wrong_notebook_root_for_markor` | 3.3% | 3.8% | +0.5 |
| `wrote_to_wrong_database_surface` | 38.8% | 39.7% | +0.8 |
| `apk_static_analysis_loop_without_db_write` | 2.2% | 4.3% | +2.2 |
| `wrong_output_value_at_correct_surface` ◇ | 12.8% | 15.2% | +2.4 |
| `permission_or_role_blocked_clipboard_or_sms` | 13.6% | 18.5% | +4.9 |

◇ = display-merged cluster (see Methods / `taxonomy.md`).
The cluster `agent_concluded_no_cli_pathway` is a presentation-layer
rename of the Phase-2 label `task_required_gui_only_no_cli_pathway`;
raw classification JSONL retains the original name for provenance.
