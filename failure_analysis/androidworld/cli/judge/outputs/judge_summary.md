# LLM Judge Results — All 211 CLI-Solvable Readable Failures

**Judge:** claude-opus-4-7, --effort max, multi-label
**Rubric:** rubric_v0.md (TB Appendix C + Android edits)
**Coverage:** 211/211 CLI-solvable readable failures (100%)

## Primary leaf distribution (single-label)

| TB leaf | n | % |
|---|---:|---:|
| weak_verification | 71 | 33.6% |
| disobey_specification | 67 | 31.8% |
| step_repetition | 28 | 13.3% |
| reasoning_action_mismatch | 14 | 6.6% |
| premature_termination | 10 | 4.7% |
| unaware_of_termination_conditions | 9 | 4.3% |
| no_or_incorrect_verification | 7 | 3.3% |
| _no_match_ | 3 | 1.4% |
| task_derailment | 2 | 0.9% |

## Multi-label prevalence (any leaf — primary or secondary)

| TB leaf | Trajectories matched | % |
|---|---:|---:|
| weak_verification | 135 | 64% |
| disobey_specification | 113 | 54% |
| step_repetition | 55 | 26% |
| reasoning_action_mismatch | 54 | 26% |
| premature_termination | 47 | 22% |
| unaware_of_termination_conditions | 45 | 21% |
| no_or_incorrect_verification | 43 | 20% |
| context_loss | 6 | 3% |
| task_derailment | 4 | 2% |
| _no_match_ | 3 | 1% |

## Per-config primary leaf distribution

| Agent / Model | n | _no_match_ | disobey_specification | no_or_incorrect_verification | premature_termination | reasoning_action_mismatch | step_repetition | task_derailment | unaware_of_termination_conditions | weak_verification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CCLI/claudeopus47 | 17 | 0 | 6 | 0 | 0 | 1 | 3 | 0 | 0 | 7 |
| CCLI/claudesonnet46 | 20 | 0 | 4 | 0 | 0 | 0 | 6 | 1 | 1 | 8 |
| MSWE/openaigpt53codex | 43 | 3 | 15 | 2 | 6 | 1 | 1 | 0 | 0 | 15 |
| MSWE/openrouterminimaxminimaxm27 | 33 | 0 | 7 | 0 | 1 | 3 | 2 | 1 | 2 | 17 |
| T2/openaigpt53codex | 40 | 0 | 16 | 2 | 3 | 2 | 1 | 0 | 0 | 16 |
| T2/openrouterminimaxminimaxm27 | 58 | 0 | 19 | 3 | 0 | 7 | 15 | 0 | 6 | 8 |

## Per-app primary leaf distribution

| App | n | _no_match_ | disobey_specification | no_or_incorrect_verification | premature_termination | reasoning_action_mismatch | step_repetition | task_derailment | unaware_of_termination_conditions | weak_verification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Calendar | 44 | 0 | 27 | 1 | 2 | 2 | 4 | 0 | 1 | 7 |
| SMS | 40 | 0 | 14 | 0 | 4 | 1 | 8 | 0 | 1 | 12 |
| Markor | 32 | 2 | 10 | 1 | 0 | 3 | 4 | 0 | 0 | 12 |
| Pro Expense | 21 | 0 | 4 | 0 | 2 | 2 | 3 | 0 | 2 | 8 |
| OsmAnd | 16 | 0 | 0 | 1 | 0 | 2 | 0 | 1 | 0 | 12 |
| Tasks app | 13 | 1 | 1 | 2 | 0 | 2 | 1 | 0 | 1 | 5 |
| Retro Music | 11 | 0 | 2 | 0 | 1 | 1 | 2 | 0 | 0 | 5 |
| VLC | 9 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 0 | 6 |
| System Settings | 7 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 1 | 2 |
| Broccoli | 6 | 0 | 0 | 1 | 1 | 1 | 1 | 0 | 1 | 1 |
| System Other | 4 | 0 | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 1 |
| Contacts | 4 | 0 | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| Other | 2 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0 |
| OpenTracks | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |

## Judge confidence distribution

- high: 128 (61%)
- low: 6 (3%)
- medium: 77 (36%)

## `_no_match_` trajectories (judge could not assign any rubric leaf)

**3 trajectories** matched none of the 9 leaves.

- **task 103 (MiniSweAgent / How many tasks do I have due next week in Tasks app? Assume )**
  rationale: The agent followed a clean procedural path: discovered device time and package, discovered the content provider schema, queried the authoritative content provider with a date-range filter for next week, and finished with the verified count. Per the Android rubric edit, content provider queries are t

- **task 22 (MiniSweAgent / Create a new folder in Markor named folder_20250808_181950.)**
  rationale: The agent executed the prescribed discover-inspect-act-verify-sync cycle cleanly in just 2 action turns: step 3 located Markor's watched directory, step 4 created the folder via `mkdir -p` with exact task name, verified existence via `ls -ld`, and force-stopped Markor to sync. For a file-based app l

- **task 87 (MiniSweAgent / Merge the contents of Markor notes copy_cool_snake.txt, back)**
  rationale: The agent performed a reasonable workflow: discovered the Markor directory (step 3), merged the three files in correct order using cat + printf '\n' separators and self-verified via cat in the same command (step 4), discovered the package name after a quoting failure (steps 5-6), force-stopped Marko
