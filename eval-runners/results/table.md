# AndroidWorld Evaluation Results

Benchmark: `val_data_seed7.jsonl` (116 tasks, seed=7)
Task split: **101 CLI-solvable** | **15 GUI-only** (per [ground truth reference](../../docs/final/AndroidWorld2026/androidworld_ground_truth_reference.md))

## Overall

| Agent | Model | Action Space | API | Overall | CLI (101) | GUI (15) | Cost |
|-------|-------|-------------|-----|--------:|----------:|---------:|-----:|
| Claude Code CLI | claude-opus-4-6 | ADB shell | Anthropic | **63.8%** (74/116) | **71.3%** (72/101) | 13.3% (2/15) | $35.89 |
| UI-Venus-1.5 | UI-Venus-1.5-30B-A3B | GUI (tap/swipe) | Local vLLM | **59.5%** (69/116) | 62.4% (63/101) | **40.0%** (6/15) | — |
| Qwen3VLAgentMCP | qwen3-vl-30b-a3b-instruct | GUI (tap/swipe) | OpenRouter | **56.0%** (65/116) | 58.4% (59/101) | **40.0%** (6/15) | — |

## CLI-Solvable Tasks (101) by Difficulty

| Difficulty | Claude Opus 4.6 | UI-Venus-1.5-30B | Qwen3-VL-30B |
|------------|----------------:|-----------------:|-------------:|
| android_easy (38) | 22/38 (58%) | 28/38 (74%) | 29/38 (76%) |
| android_medium (26) | 18/26 (69%) | 14/26 (54%) | 10/26 (38%) |
| android_hard (12) | 7/12 (58%) | 4/12 (33%) | 5/12 (42%) |
| info_easy (14) | **14/14 (100%)** | 10/14 (71%) | 9/14 (64%) |
| info_medium (8) | **8/8 (100%)** | 7/8 (88%) | 5/8 (62%) |
| info_hard (3) | **3/3 (100%)** | 0/3 (0%) | 1/3 (33%) |

## GUI-Only Tasks (15) by Difficulty

| Difficulty | Claude Opus 4.6 | UI-Venus-1.5-30B | Qwen3-VL-30B |
|------------|----------------:|-----------------:|-------------:|
| android_easy (9) | 1/9 (11%) | 5/9 (56%) | 5/9 (56%) |
| android_medium (2) | 0/2 (0%) | 1/2 (50%) | 1/2 (50%) |
| android_hard (4) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) |

## Key Observations

- **Claude Opus 4.6 dominates information-retrieval tasks** — 100% (25/25) across all IR difficulties via direct database/file queries.
- **UI-Venus-1.5-30B ranks second overall (59.5%)** — strong on easy tasks (74% CLI easy) and competitive on GUI-only tasks (40.0%), matching Qwen3-VL.
- **Qwen3-VL and UI-Venus tie on GUI-only tasks** — both at 40.0% (6/15), with identical per-difficulty breakdowns.
- **Claude CLI excels at medium/hard action tasks** — 69% vs 54% (Venus) vs 38% (Qwen) on android_medium CLI tasks, leveraging ADB + content providers + sqlite3.
- **GUI-only tasks are Claude CLI's weakness** — 13.3% vs 40.0%, as expected for a text-only agent on tasks requiring visual interaction.

## Run Details

| | Claude Opus 4.6 | UI-Venus-1.5-30B | Qwen3-VL-30B |
|--|-----------------|------------------|--------------|
| Date | 2026-04-08 | 2026-04-08 | 2026-04-07 |
| Runner | `run_claude_cli.py` | `run_venus.py` | `run_qwen3vl.py` |
| Prompt/Agent | `clean_optimized` | `VenusNaviAgent` | `Qwen3VLAgentMCP` |
| Max turns/steps | 30 | 30 | 30 |
| Avg steps/task | 12.7 | 14.2 | 11.7 |
| Temperature | — | 0.0 | 0.0 |
| Avg time/task | 91s | 102s | 135s |
| Input tokens | — | 5,481,319 | 4,980,891 |
| Output tokens | — | 187,728 | 160,289 |
| Results dir | `ClaudeCodeCLI_claudeopus46_260408_0122/` | `UIVenus15_30BA3B_260408/` | `ClaudeCodeCLI_qwenqwen3vl30ba3binstruct_260407_2117/` |

GUI-only task IDs: 0, 1, 8, 20, 28, 29, 30, 37, 40, 47, 55, 75, 76, 78, 80
