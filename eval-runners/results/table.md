# AndroidWorld Evaluation Results

Benchmark: `val_data_seed7.jsonl` (116 tasks, seed=7)
Task split: **101 CLI-solvable** | **15 GUI-only** (per [ground truth reference](../../docs/final/AndroidWorld2026/androidworld_ground_truth_reference.md))

## Overall

| Agent | Model | Action Space | API | Overall | CLI (101) | GUI (15) | Cost |
|-------|-------|-------------|-----|--------:|----------:|---------:|-----:|
| Claude Code CLI | claude-opus-4-6 | ADB shell | Anthropic | **63.8%** (74/116) | **71.3%** (72/101) | 13.3% (2/15) | $35.89 |
| UI-Venus-1.5 | UI-Venus-1.5-30B-A3B | GUI (tap/swipe) | Local vLLM | **59.5%** (69/116) | 62.4% (63/101) | **40.0%** (6/15) | — |
| Qwen3VLAgentMCP | qwen3-vl-30b-a3b-instruct | GUI (tap/swipe) | OpenRouter | **56.0%** (65/116) | 58.4% (59/101) | **40.0%** (6/15) | — |
| Terminus2 | minimax-m2.7 | ADB shell | OpenRouter | **52.6%** (61/116) | 58.4% (59/101) | 13.3% (2/15) | $5.82 |
| MAI-UI | MAI-UI-8B | GUI (tap/swipe) | Local vLLM | **31.0%** (36/116) | 33.7% (34/101) | 13.3% (2/15) | — |
| GeneralE2E | gemini-2.5-pro | GUI (tap/swipe) | OpenRouter | **13.8%** (16/116) | 13.9% (14/101) | 13.3% (2/15) | — |

## CLI-Solvable Tasks (101) by Difficulty

| Difficulty | Claude Opus 4.6 | UI-Venus-1.5-30B | Qwen3-VL-30B | Terminus2 m2.7 | MAI-UI-8B | Gemini 2.5 Pro |
|------------|----------------:|-----------------:|-------------:|---------------:|----------:|---------------:|
| android_easy (38) | 22/38 (58%) | 28/38 (74%) | 29/38 (76%) | 23/38 (61%) | 16/38 (42%) | 8/38 (21%) |
| android_medium (26) | 18/26 (69%) | 14/26 (54%) | 10/26 (38%) | 16/26 (62%) | 6/26 (23%) | 2/26 (8%) |
| android_hard (12) | 7/12 (58%) | 4/12 (33%) | 5/12 (42%) | 3/12 (25%) | 1/12 (8%) | 0/12 (0%) |
| info_easy (14) | **14/14 (100%)** | 10/14 (71%) | 9/14 (64%) | 10/14 (71%) | 5/14 (36%) | 3/14 (21%) |
| info_medium (8) | **8/8 (100%)** | 7/8 (88%) | 5/8 (62%) | 4/8 (50%) | 4/8 (50%) | 1/8 (12%) |
| info_hard (3) | **3/3 (100%)** | 0/3 (0%) | 1/3 (33%) | 3/3 (100%) | 2/3 (67%) | 0/3 (0%) |

## GUI-Only Tasks (15) by Difficulty

| Difficulty | Claude Opus 4.6 | UI-Venus-1.5-30B | Qwen3-VL-30B | Terminus2 m2.7 | MAI-UI-8B | Gemini 2.5 Pro |
|------------|----------------:|-----------------:|-------------:|---------------:|----------:|---------------:|
| android_easy (9) | 1/9 (11%) | 5/9 (56%) | 5/9 (56%) | 1/9 (11%) | 2/9 (22%) | 2/9 (22%) |
| android_medium (2) | 0/2 (0%) | 1/2 (50%) | 1/2 (50%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) |
| android_hard (4) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) |

## Key Observations

- **Claude Opus 4.6 dominates information-retrieval tasks** — 100% (25/25) across all IR difficulties via direct database/file queries.
- **UI-Venus-1.5-30B ranks second overall (59.5%)** — strong on easy tasks (74% CLI easy) and competitive on GUI-only tasks (40.0%), matching Qwen3-VL.
- **Qwen3-VL and UI-Venus tie on GUI-only tasks** — both at 40.0% (6/15), with identical per-difficulty breakdowns.
- **Claude CLI excels at medium/hard action tasks** — 69% vs 54% (Venus) vs 38% (Qwen) on android_medium CLI tasks, leveraging ADB + content providers + sqlite3.
- **GUI-only tasks are Claude CLI's weakness** — 13.3% vs 40.0%, as expected for a text-only agent on tasks requiring visual interaction.

## Run Details

| | Claude Opus 4.6 | UI-Venus-1.5-30B | Qwen3-VL-30B | Terminus2 m2.7 | MAI-UI-8B | Gemini 2.5 Pro |
|--|-----------------|------------------|--------------|----------------|-----------|----------------|
| Date | 2026-04-08 | 2026-04-08 | 2026-04-07 | 2026-04-08 | 2026-04-08 | 2026-04-08 |
| Runner | `run_claude_cli.py` | `run_venus.py` | `run_qwen3vl.py` | `run_terminus2.py` | `run_mai.py` | `run_general_e2e.py` |
| Prompt/Agent | `clean_optimized` | `VenusNaviAgent` | `Qwen3VLAgentMCP` | `optimized-v2` | `MAIUINaivigationAgent` | `GeneralE2EAgentMCP` |
| Max turns/steps | 30 | 30 | 30 | 30 | 30 | 30 |
| Avg steps/task | 12.7 | 14.2 | 11.7 | 14.0 | 21.1 | 25.8 |
| Temperature | — | 0.0 | 0.0 | 0.7 | 0.0 | 0.0 |
| Avg time/task | 91s | 102s | 135s | 168s | 267s | 282s |
| Avg input tokens/task | 325,196 | 47,252 | 42,938 | 288,128 | 191,868 | 75,405 |
| Avg output tokens/task | 2,799 | 1,618 | 1,381 | 4,107 | 2,079 | 2,667 |
| Results dir | `ClaudeCodeCLI_claudeopus46_260408_0122/` | `UIVenus15_30BA3B_260408/` | `ClaudeCodeCLI_qwenqwen3vl30ba3binstruct_260407_2117/` | `ClaudeCodeCLI_openrouterminimaxminimaxm27_260408_0207/` | `MAIUI8B_260408/` | `ClaudeCodeCLI_googlegemini25pro_260408_*` |

GUI-only task IDs: 0, 1, 8, 20, 28, 29, 30, 37, 40, 47, 55, 75, 76, 78, 80

---

# MobileWorld Evaluation Results

Benchmark: `gui_only_tasks.jsonl` (117 GUI-only tasks)

## Overall

| Agent | Model | Action Space | API | SR | Paper SR |
|-------|-------|-------------|-----|---:|--------:|
| GeneralE2E | Kimi K2.5 | GUI (tap/swipe) | OpenRouter | **37.6%** (44/117) | 49.6% |
| UI-Venus-1.5 | UI-Venus-1.5-30B-A3B | GUI (tap/swipe) | Local vLLM | **11.1%** (13/117) | 17.1% |
| MAI-UI | MAI-UI-8B | GUI (tap/swipe) | Local vLLM | **6.0%** (7/117) | 27.5% |

### Paper Reference (MobileWorld Leaderboard, GUI-Only, max_steps=50)

| Model | Organization | GUI-Only | User-Int. | MCP |
|-------|-------------|--------:|---------:|----:|
| Seed-2.0-Pro | ByteDance | **63.2%** | 61.4% | — |
| GPT-5 + UI-Ins-7B | OpenAI | 54.0% | 62.2% | 51.6% |
| Gemini-3-Pro + UI-Ins-7B | Google | 55.6% | 24.4% | 48.6% |
| Gemini-3-Pro | Google | 51.3% | 29.5% | — |
| Seed-1.8 | ByteDance | 52.1% | 29.5% | — |
| Kimi-K2.5 | Moonshot AI | 49.6% | 51.2% | — |
| Claude-4.5-Sonnet | Anthropic | 47.8% | 38.6% | — |
| GUI-Owl-1.5-32B | Alibaba | 43.9% | 56.1% | 42.5% |
| Qwen3.5-397B-A17B | Alibaba | 42.7% | 54.4% | — |
| MAI-UI-235B-A22B | Alibaba | 39.7% | 51.1% | 37.5% |
| GUI-Owl-1.5-8B | Alibaba | 38.2% | 53.8% | 37.5% |
| MAI-UI-32B | Alibaba | 36.2% | 46.7% | 30.0% |
| Qwen3.5-122B-A10B | Alibaba | 35.0% | 40.9% | — |
| MAI-UI-8B | Alibaba | 27.5% | 22.2% | 20.0% |
| Doubao-1.5-UI-TARS | ByteDance | 26.3% | 32.4% | — |
| UI-Venus-1.5-30B-A3B | Ant Group | 17.1% | — | — |
| UI-Venus-72B | Ant Group | 16.4% | — | — |
| GELab-Zero-4B | StepFun-AI | 16.1% | 6.7% | — |
| Qwen3-VL-235B-A22B | Alibaba | 12.8% | 4.4% | 5.4% |
| Qwen3-VL-32B | Alibaba | 11.9% | 6.7% | 2.7% |
| Qwen3-VL-8B | Alibaba | 9.4% | 0.0% | 0.0% |
| UI-Venus-7B | Ant Group | 8.5% | — | — |

*Source: [MobileWorld Leaderboard](https://tongyi-mai.github.io/MobileWorld/#leaderboard) (accessed 2026-04-08)*

## Successful Tasks (UI-Venus-1.5-30B-A3B)

| Task | Steps | Time |
|------|------:|-----:|
| AcceptMeetingTask | 8 | 66s |
| AdjustBrightnessMaximumTask | 7 | 61s |
| AdjustBrightnessMinimumTask | 6 | 57s |
| CancelMeetingTask | 7 | 61s |
| ChangeWallpaperTask | 9 | 71s |
| CheckEventTimeTask | 14 | 69s |
| CheckInvoiceTask3 | 19 | 101s |
| CheckPuchasedItem | 11 | 57s |
| ChromeSearchBeijingWeatherTask | 10 | 55s |
| CloseFlightModeTask | 4 | 28s |
| MastodonFollowTask | 16 | 114s |
| MastodonNewPostTask | 7 | 74s |
| MastodonReplyTask | 30 | 178s |

## Run Details

| | Kimi K2.5 | UI-Venus-1.5-30B |
|--|-----------|------------------|
| Date | 2026-04-08 | 2026-04-08 |
| Runner | `run_gui_agent_broker.py` | `run_gui_agent_broker.py` |
| Agent type | `general_e2e` | `ui_venus_agent` |
| Max steps | 50 | 50 |
| Avg steps/task | 23.5 | 18.7 |
| Temperature | 0.0 | 0.0 |
| Avg time/task | 265s | 111s |
| Avg input tokens/task | 290,828 | 24,554 |
| Avg output tokens/task | 2,909 | 655 |
| Results dir | `GUIAgent_general_e2e_moonshotaikimik25_260408_0252/` | `GUIAgent_ui_venus_agent_UIVenus1530BA3B_260408_0157/` |
