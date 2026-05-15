# Heuristic Pattern Clustering — All 126 Failures

> **Exploratory only.** Pattern detectors are regex/string heuristics derived from
> the 10-trajectory blind read. NOT rubric labels — those come from Phase 3+4.
> Use this to spot signal/clusters early and validate that the patterns from the
> 10-sample generalize.

**Pool:** 126 failures from `pilot_set.jsonl`

## Primary cluster distribution

| Cluster | Count | % |
|---|---:|---:|
| unclassified | 75 | 59.5% |
| honest_infeasibility | 15 | 11.9% |
| verify_through_same_surface | 13 | 10.3% |
| self_prompt_violation_apk | 5 | 4.0% |
| wrong_surface__mediastore_for_app_specific_player | 5 | 4.0% |
| wrong_surface__app_db_no_mapping_recovery | 4 | 3.2% |
| shell_quoting_fight | 4 | 3.2% |
| wrong_surface__app_db_for_system_provider_task | 3 | 2.4% |
| hit_max_turns | 2 | 1.6% |

## Per-flag prevalence (multiple flags can coexist)

| Flag | Count | % |
|---|---:|---:|
| `quoting_retries` | 10 | 7.9% |
| `self_verify_same_db` | 21 | 16.7% |
| `apk_extraction` | 5 | 4.0% |
| `no_finish_call` | 67 | 53.2% |
| `infeasibility_admitted` | 21 | 16.7% |
| `hit_max_turns` | 4 | 3.2% |

**Wrong-surface breakdown:**

| Surface kind | Count |
|---|---:|
| `mediastore_for_app_specific_player` | 5 |
| `app_db_no_mapping_recovery` | 4 |
| `app_db_for_system_provider_task` | 3 |

## Per-config cluster distribution

| Config | hit_max_turns | honest_infeasibility | self_prompt_violation_apk | shell_quoting_fight | unclassified | verify_through_same_surface | wrong_surface__app_db_for_system_provider_task | wrong_surface__app_db_no_mapping_recovery | wrong_surface__mediastore_for_app_specific_player | total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ClaudeCodeCLI claudeopus47 seed30 bash only | 2 | 1 | 3 | 0 | 20 | 4 | 0 | 1 | 0 | 31 |
| MiniSweAgent openaigpt53codex seed30 bash only | 0 | 10 | 0 | 3 | 39 | 2 | 0 | 1 | 4 | 59 |
| Terminus2 openrouterminimaxminimaxm27 seed30 bash only | 0 | 4 | 2 | 1 | 16 | 7 | 3 | 2 | 1 | 36 |

## Per-config raw flag counts

| Config | quoting_retries | self_verify_same_db | apk_extraction | no_finish_call | infeasibility_admitted | hit_max_turns |
|---|---:|---:|---:|---:|---:|---:|
| ClaudeCodeCLI claudeopus47 seed30 bash only | 0 | 5 | 3 | 31 | 1 | 4 |
| MiniSweAgent openaigpt53codex seed30 bash only | 4 | 3 | 0 | 0 | 11 | 0 |
| Terminus2 openrouterminimaxminimaxm27 seed30 bash only | 6 | 13 | 2 | 36 | 9 | 0 |

## Top flag co-occurrences

| Flag A | Flag B | Count |
|---|---|---:|
| `self_verify_same_db` | `no_finish_call` | 18 |
| `no_finish_call` | `infeasibility_admitted` | 10 |
| `quoting_retries` | `no_finish_call` | 6 |
| `apk_extraction` | `no_finish_call` | 5 |
| `self_verify_same_db` | `infeasibility_admitted` | 5 |
| `no_finish_call` | `hit_max_turns` | 4 |
| `quoting_retries` | `self_verify_same_db` | 4 |
| `quoting_retries` | `infeasibility_admitted` | 3 |
| `apk_extraction` | `hit_max_turns` | 2 |
| `self_verify_same_db` | `apk_extraction` | 1 |
| `apk_extraction` | `infeasibility_admitted` | 1 |

## Caveats

- Detectors are heuristic; precision/recall unknown until calibrated.
- `no_finish_call` is sensitive to format quirks — Terminus2 trajectories may
  end without a recorded finish even when the agent intended to terminate.
- `wrong_surface_kind` triggers on combinations of (write target × task keyword).
  False positives are likely on tasks where multiple surfaces are valid.
- `self_verify_same_db` only catches direct sqlite3 patterns; provider-based
  self-verification (insert+query through the same `content://`) is missed.
- `infeasibility_admitted` matches generic phrases; agents may say 'unable to'
  about a sub-task while actually completing the main task. Manual review needed.