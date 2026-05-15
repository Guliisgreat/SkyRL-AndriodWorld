# v2 Rubric Validation — Two-Annotator Packet (Docent-first)

**Pool:** 15 trajectories sampled from 211 CLI-solvable readable failures.
**Docent collection:** https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954

**Read each trajectory in the Docent UI** using the links below. The UI renders each agent step + observation natively, supports navigation, and shows the LLM judge's existing readings (v1 and v2) — but please **do not consult those before forming your independent annotation**.

After reading, fill in your annotation in `v2_validation_results.csv` (one row per trajectory, two columns per annotator).

## v2 leaf reference (one-line summaries)

- **disobey_specification** — wrong consumer surface / wrong API level / wrong output format / fabricated data when source named / forbidden ops
- **step_repetition** — same ADB command class against same target ≥ 2× without strategy change
- **unaware_of_termination_conditions** — continued past Android success/futility signal (C1 or C2)
- **context_loss** — forgot established device state or task content within a recent window
- **task_derailment** — sub-goal drifted from primary objective for ≥ 2 turns
- **reasoning_action_mismatch** — reasoning vs action: declared method ≠ actual, uncertainty-then-commit, intent vs encoded-command
- **premature_termination** — finish before objectives met; positive PT (claimed success) or negative PT (gave up empty)
- **no_or_incorrect_verification** — completed without any substantive read against authoritative surface
- **weak_verification** — verified, but via wrong surface (same-surface read after write; provider-notification gap)
- **_no_match_** — none of the above (rare; explain)

Read the full v2 rubric at `failure_analysis/androidworld/cli/rubric/rubric_v2.md` before starting.

## The 15 trajectories

| # | Task | Agent | Steps | Docent link |
|---:|---:|---|---:|---|
| 1 | 83 | Terminus2 | 4/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/7d6d0b08-ccbf-44e2-8daa-bb3d0c54448d) — Create a playlist in Retro Music titled "Party Mix 553" with |
| 2 | 79 | ClaudeCodeCLI | 35/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/1635544c-1dbd-4e56-8e8f-e38a7356177d) — Create a new note in Markor named copy_cool_snake.txt with t |
| 3 | 53 | ClaudeCodeCLI | 22/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/26c72bc6-e824-4429-a585-c52910b80a99) — Create a note in Markor named copy_cool_snake.txt. Perform a |
| 4 | 48 | Terminus2 | 23/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/891a5f07-cce5-4cbd-9153-fb1251d3cef6) — Add the following expenses into the pro expense: name|amount |
| 5 | 87 | MiniSweAgent | 5/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/c2c3073f-f541-427d-84db-83517b68f34f) — Merge the contents of Markor notes copy_cool_snake.txt, back |
| 6 | 32 | Terminus2 | 0/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/2cd942df-8a31-48ee-9c22-d19bbabdd713) — Delete the following recipes from Broccoli app: Classic Marg |
| 7 | 13 | Terminus2 | 0/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/ccd6f761-e3b7-46b7-8c57-7bd667c7dcc3) — Delete the note in Markor named copy_cool_snake. |
| 8 | 6 | MiniSweAgent | 10/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/d6c04cd6-8ae4-4dfa-9f32-2fad3dac7c2e) — In Simple Calendar Pro, delete the calendar event on 2023-10 |
| 9 | 102 | Terminus2 | 22/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/eac0fcd9-905b-47aa-9c6b-ac3e82980ab5) — Which tasks with high priority are due the Monday after next |
| 10 | 48 | MiniSweAgent | 16/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/a1f2c223-5650-4371-af79-a1a68e788e71) — Add the following expenses into the pro expense: name|amount |
| 11 | 73 | Terminus2 | 46/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/068cd368-69f9-4ed2-a1f4-5a633700aed6) — Create a playlist titled "Mystery and Thrills Series" with t |
| 12 | 56 | Terminus2 | 10/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/dfde8650-d174-47fd-ada0-e9779b951c25) — Add the following recipes into the Broccoli app: Recipe: Kal |
| 13 | 39 | ClaudeCodeCLI | 50/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/c831b017-7461-4e6d-a8ec-150994958262) — Send a message to +18490934066 with the clipboard content in |
| 14 | 10 | MiniSweAgent | 2/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/45af05c8-534f-41fb-b8df-5338259e124b) — Go to the new contact screen and enter the following details |
| 15 | 22 | ClaudeCodeCLI | 7/50 | [Open](https://docent.transluce.org/dashboard/bb2d8166-2a47-4b8b-80d1-27dcd7603954/agent_run/37df4e68-2138-4409-907f-38d9ae8c7bf0) — Create a new folder in Markor named folder_20250808_181950. |

## Annotation template (one entry per trajectory)

Fill in the CSV `v2_validation_results.csv`. Each annotator gets a separate column set.
Required fields per annotator:
- `primary_leaf` (one of the 9 v2 leaves or `_no_match_`)
- `secondary_leaves` (comma-separated list, possibly empty)
- `confidence` (low/medium/high)
- `rationale` (1-2 sentences citing specific step numbers)

## Collaborative annotation in Docent UI

Docent supports two collaborative features per agent run:

1. **Comments** — every agent run page has a comment thread at the bottom of the right panel. Teammates can leave discussion notes ("why did the agent do X?", "this looks like RAM not DS") that are visible to everyone with collection access.
2. **Labels** — teammates with collection access can apply structured labels to each agent run. For this validation, apply a label corresponding to your chosen v2 primary leaf (e.g., `v2/disobey_specification`).

**Teammate access:** add your collaborators to the Docent organization at https://docent.transluce.org/settings/team, then grant access to this collection. They will be able to view, comment on, and label the agent runs.

## After both annotators finish

Reveal `v2_validation_picks_hidden.jsonl` to see the v2 LLM judge's picks and rationales. Compute:
- Cohen's κ on `primary_leaf` (A vs B) — inter-annotator agreement (target ≥ 0.6)
- Cohen's κ on `primary_leaf` (each annotator vs v2 LLM judge) — target ≥ 0.6