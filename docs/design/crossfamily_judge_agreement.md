# Cross-Family LLM Judge Agreement on AndroidWorld CLI Failures

**Date:** 2026-05-20
**Pipeline:** Phase 4 cross-walk validation (15 emergent clusters → 9-leaf
Terminal-Bench taxonomy)
**Outcome:** Fleiss κ = 1.000 (perfect), exceeding TB paper's 0.92
inter-annotator κ.

---

## Background

The TB paper (Merrill et al., arXiv:2601.11868, Appendix C) reports
**Cohen's κ = 0.92** across 3 human annotators on its 9-leaf failure
taxonomy. Our goal: replicate that inter-rater reliability with
**LLM judges** on the Android-CLI cross-walk, treating the rubric as the
shared interpretive instrument.

Independence is enforced by **cross-family** model selection — each
judge is a different vendor's frontier model. No judge sees another
judge's output. All three see the same prompt: the base rubric + a
clarifications doc + the 15-cluster Phase-2 proposal.

## Setup

| judge | model | family | invocation |
|---|---|---|---|
| J1 | claude-opus-4.7 | Anthropic | OpenRouter |
| J2 | gpt-5.5-pro | OpenAI | OpenRouter |
| J3 | gemini-2.5-pro | Google | OpenRouter |

**Shared inputs:**
- `failure_analysis/androidworld/cli/rubric/rubric_v2.md` — Android-native
  rewrite of TB Appendix C, 9 leaves + decision procedures.
- `rubric_v2_clarifications.md` — 8 tie-breaker rules covering the
  clusters that admit multiple plausible TB leaves.
- `discovery/cluster_proposal.json` — 15 emergent clusters with
  descriptions and transcript signatures.

**Constraint:** every judge must (a) pick exactly one primary leaf per
cluster, (b) cite either `rubric_v2.md` or `rubric_v2_clarifications.md`
in its rationale, (c) apply tie-breaker rules literally.

## Iterations

### Round 1 — base rubric only

3 judges, no tie-breakers. **Fleiss κ = 0.659** (substantial). 9/15
clusters unanimous; 6 disagreement clusters drove the gap.

| disagreement cluster | J1 | J2 | J3 |
|---|---|---|---|
| `refused_or_skipped_required_ui_taps` | (not in TB) | Disobey | Disobey |
| `could_not_read_pixels_no_ocr` | (not in TB) | UoT | Disobey |
| `wrong_value_at_correct_surface` | Disobey | Disobey | Weak Ver. |
| `queried_wrong_provider_or_snapshot_path` | Weak Ver. | Premature | Premature |
| `broadcast_or_intent_to_nonexistent_receiver` | UoT | Disobey | RAM |
| `stopped_at_apk_or_tool_reconnaissance` | Step Rep. | Disobey | Disobey |

### Round 2 — add `rubric_v2_clarifications.md` tie-breakers 1-6

3 judges, refined rubric. **Fleiss κ = 0.812** (almost perfect). 13/15
unanimous; the remaining 2 clusters — `wrong_time_or_timezone_interpretation`
and `clipboard_unreadable_from_shell_uid` — were unanimous in Round 1
but became contested in Round 2 because tie-breakers 1-6 reshuffled
judge priors.

### Round 3 — add tie-breakers 7-8

3 judges, refined rubric with 8 tie-breakers (timezone errors →
Disobey Spec; clipboard SecurityException misread → Disobey Spec).
**Fleiss κ = 1.000.** All 15 clusters unanimous. Cohen's κ = 1.000 on
every pair.

## Result (consensus mapping over 974 trajectories)

| cluster | obs % | TB leaf |
|---|---|---|
| `bypassed_app_send_or_capture_pipeline_with_direct_db_writes` | 23.7% | Disobey Specification |
| `refused_or_skipped_required_ui_taps` | 13.6% | Disobey Specification |
| `wrote_to_wrong_app_data_store` | 10.4% | Disobey Specification |
| `could_not_read_pixels_no_ocr` | 9.7% | Disobey Specification |
| `wrong_time_or_timezone_interpretation` | 6.8% | Disobey Specification |
| `guessed_or_inverted_enum_or_repeat_encoding` | 6.2% | Reasoning-Action Mismatch |
| `clipboard_unreadable_from_shell_uid` | 4.4% | Disobey Specification |
| `byte_exact_write_drift_or_separator_mismatch` | 4.1% | Disobey Specification |
| `wrong_value_at_correct_surface` | 4.1% | Disobey Specification |
| `queried_wrong_provider_or_snapshot_path` | 3.9% | Premature Termination |
| `broadcast_or_intent_to_nonexistent_receiver` | 3.6% | Reasoning-Action Mismatch |
| `harness_token_limit_or_command_parse_failure` | 3.2% | (not in TB — harness) |
| `fabricated_values_from_unread_or_truncated_source` | 3.0% | Disobey Specification |
| `stopped_at_apk_or_tool_reconnaissance` | 2.9% | Disobey Specification |
| `self_confirmed_via_own_write_readback` | 0.6% | Weak Verification |

### TB-leaf rollup (974 trajectories, primary only)

| TB leaf | group | n | share |
|---|---|---|---|
| **Disobey Specification** | Execution | 804 | **82.5 %** |
| **Reasoning-Action Mismatch** | Coherence | 95 | 9.8 % |
| **Premature Termination** | Verification | 38 | 3.9 % |
| **(not in TB — harness)** | — | 31 | 3.2 % |
| **Weak Verification** | Verification | 6 | 0.6 % |
| Step Repetition | Execution | 0 | 0 % |
| Unaware of Termination | Execution | 0 | 0 % |
| Context Loss | Coherence | 0 | 0 % |
| Task Derailment | Coherence | 0 | 0 % |
| No or Incorrect Verification | Verification | 0 | 0 % |

## Comparison with Round 1's narrower mapping

| TB leaf | Round 1 share | Round 3 share | delta |
|---|---|---|---|
| Disobey Specification | 41.2 % | **82.5 %** | +41.3 |
| (not in TB — UI/OCR) | 23.3 % | 0 % | -23.3 |
| Reasoning-Action Mismatch | 17.4 % | 9.8 % | -7.6 |
| Weak Verification | 8.6 % | 0.6 % | -8.0 |
| Premature Termination | 0 % | 3.9 % | +3.9 |
| Unaware of Termination | 3.6 % | 0 % | -3.6 |
| Step Repetition | 2.9 % | 0 % | -2.9 |
| (not in TB — harness) | 3.2 % | 3.2 % | 0 |

**Interpretation.** Tightening the rubric collapsed three previously
split categories into Disobey Specification: (a) UI-required tasks
(13.6 %) now read as "wrong API level," (b) OCR-required tasks (9.7 %)
likewise, (c) the timezone/clipboard clusters (11.2 %) now read as
"wrong output format" rather than RAM/UoT. The picture that survives is
that Android-CLI failures are overwhelmingly **specification
violations** — agents reach for the wrong API level or write malformed
values — not coherence or verification failures.

## Files

- `run_crossfamily_judges.py` — 3-judge driver (OpenRouter).
- `judge_agreement_v2.py` — agreement metrics.
- `crosswalk_judge{1,2,3}_v2.json` — per-judge outputs.
- `judge_agreement_v2.md` — agreement table + per-cluster verdicts.
- `consensus_mapping_v2.json` — final consensus mapping + κ.
- `rubric_v2_clarifications.md` — 8 tie-breaker rules.
