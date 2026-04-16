# AndroidWorld Evaluation Results

Benchmark: `val_data_seed7.jsonl` (116 tasks, seed=7) unless noted
Task split: **101 CLI-solvable** | **15 GUI-only** (per [ground truth reference](../../docs/final/AndroidWorld2026/androidworld_ground_truth_reference.md))

## Overall

| Agent | Model | Action Space | API | Overall | CLI (101) | GUI (15) | Cost |
|-------|-------|-------------|-----|--------:|----------:|---------:|-----:|
| MAI-UI (ref-faithful)† | MAI-UI-8B | GUI (dir swipe) | Local vLLM | **69.0%** (80/116) | 73.3% (74/101) | 40.0% (6/15) | — |
| GUI-Owl-1.5 (ref-faithful)† | GUI-Owl-1.5-32B-Instruct | GUI (pixel swipe) | Local vLLM | **69.0%** (80/116) | 71.3% (72/101) | **53.3%** (8/15) | — |
| UI-Venus-1.5-8B (ref, 50×)† | UI-Venus-1.5-8B | GUI (pixel swipe) | Local vLLM | **68.1%** (79/116) | 73.3% (74/101) | 33.3% (5/15) | — |
| UI-Venus-1.5-30B (ref-faithful)† | UI-Venus-1.5-30B-A3B | GUI (pixel swipe) | Local vLLM | **67.2%** (78/116) | 69.3% (70/101) | **53.3%** (8/15) | — |
| UI-Venus-1.5-8B (ref-faithful)† | UI-Venus-1.5-8B | GUI (pixel swipe) | Local vLLM | **67.2%** (78/116) | 72.3% (73/101) | 33.3% (5/15) | — |
| Claude Code CLI | claude-opus-4-6 | ADB shell | Anthropic | **63.8%** (74/116) | **71.3%** (72/101) | 13.3% (2/15) | $35.89 |
| Gemini 3.1 Pro† | gemini-3.1-pro-preview | GUI (pixel swipe) | OpenRouter | **61.2%** (71/116) | — | — | — |
| Qwen3-VL-32B† | qwen3-vl-32b-instruct | GUI (pixel swipe) | OpenRouter | **58.6%** (68/116) | 64.4% (65/101) | 20.0% (3/15) | — |
| UI-Venus-1.5 (32k) | UI-Venus-1.5-30B-A3B | GUI (tap/swipe) | Local vLLM | **60.3%** (70/116) | 63.4% (64/101) | **40.0%** (6/15) | — |
| UI-Venus-1.5 (8k) | UI-Venus-1.5-30B-A3B | GUI (tap/swipe) | Local vLLM | **59.5%** (69/116) | 62.4% (63/101) | **40.0%** (6/15) | — |
| Qwen3VLAgentMCP | qwen3-vl-30b-a3b-instruct | GUI (tap/swipe) | OpenRouter | **56.0%** (65/116) | 58.4% (59/101) | **40.0%** (6/15) | — |
| GUI-Owl-1.5 | GUI-Owl-1.5-32B-Instruct | GUI (tap/swipe) | Local vLLM | **55.2%** (64/116) | 57.4% (58/101) | **40.0%** (6/15) | — |
| Terminus2 | minimax-m2.7 | ADB shell | OpenRouter | **52.6%** (61/116) | 58.4% (59/101) | 13.3% (2/15) | $5.82 |
| MAI-UI (vllm 0.11) | MAI-UI-8B | GUI (tap/swipe) | Local vLLM | **69.8%** (81/116) | 72.3% (73/101) | **53.3%** (8/15) | — |
| MAI-UI (vllm 0.13) | MAI-UI-8B | GUI (tap/swipe) | Local vLLM | **31.0%** (36/116) | 33.7% (34/101) | 13.3% (2/15) | — |
| GeneralE2E | gemini-2.5-pro | GUI (tap/swipe) | OpenRouter | **13.8%** (16/116) | 13.9% (14/101) | 13.3% (2/15) | — |

## CLI-Solvable Tasks (101) by Difficulty

| Difficulty | Claude Opus 4.6 | Venus-1.5 (32k) | Venus-1.5 (8k) | Qwen3-VL-30B | GUI-Owl-1.5-32B | Terminus2 m2.7 | MAI-UI-8B (0.11) | MAI-UI-8B (0.13) | Gemini 2.5 Pro |
|------------|----------------:|----------------:|---------------:|-------------:|----------------:|---------------:|-----------------:|-----------------:|---------------:|
| android_easy (38) | 22/38 (58%) | 30/38 (79%) | 28/38 (74%) | 29/38 (76%) | 29/38 (76%) | 23/38 (61%) | **33/38 (87%)** | 16/38 (42%) | 8/38 (21%) |
| android_medium (26) | 18/26 (69%) | 12/26 (46%) | 14/26 (54%) | 10/26 (38%) | 8/26 (31%) | 16/26 (62%) | 17/26 (65%) | 6/26 (23%) | 2/26 (8%) |
| android_hard (12) | 7/12 (58%) | 5/12 (42%) | 4/12 (33%) | 5/12 (42%) | 4/12 (33%) | 3/12 (25%) | 5/12 (42%) | 1/12 (8%) | 0/12 (0%) |
| info_easy (14) | **14/14 (100%)** | 10/14 (71%) | 10/14 (71%) | 9/14 (64%) | 9/14 (64%) | 10/14 (71%) | 12/14 (86%) | 5/14 (36%) | 3/14 (21%) |
| info_medium (8) | **8/8 (100%)** | 6/8 (75%) | 7/8 (88%) | 5/8 (62%) | 7/8 (88%) | 4/8 (50%) | 5/8 (62%) | 4/8 (50%) | 1/8 (12%) |
| info_hard (3) | **3/3 (100%)** | 1/3 (33%) | 0/3 (0%) | 1/3 (33%) | 1/3 (33%) | 3/3 (100%) | 1/3 (33%) | 2/3 (67%) | 0/3 (0%) |

## GUI-Only Tasks (15) by Difficulty

| Difficulty | Claude Opus 4.6 | Venus-1.5 (32k) | Venus-1.5 (8k) | Qwen3-VL-30B | GUI-Owl-1.5-32B | Terminus2 m2.7 | MAI-UI-8B (0.11) | MAI-UI-8B (0.13) | Gemini 2.5 Pro |
|------------|----------------:|----------------:|---------------:|-------------:|----------------:|---------------:|-----------------:|-----------------:|---------------:|
| android_easy (9) | 1/9 (11%) | 6/9 (67%) | 5/9 (56%) | 5/9 (56%) | 6/9 (67%) | 1/9 (11%) | **8/9 (89%)** | 2/9 (22%) | 2/9 (22%) |
| android_medium (2) | 0/2 (0%) | 0/2 (0%) | 1/2 (50%) | 1/2 (50%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) |
| android_hard (4) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) | 0/4 (0%) | 0/4 (0%) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) | 0/4 (0%) |

## Key Observations

- **GUI-Owl-1.5 (ref-faithful) achieves 69.0%** — matches the reference in-process result (68.1%) via HTTP. Uses `val_data_refseed30.jsonl` (per-task seeds from reference), multi-turn conversation with `convert_format()`, pixel-coordinate swipe, and `androidworld:2026plusswipe` Docker image. Paper reports 69.8%.
- **MAI-UI-8B (vllm 0.11) at 69.8%** — massive improvement over 31.0% with vllm 0.13. The vllm version critically affects model behavior; **vllm 0.11.0 is required** for correct MAI-UI-8B inference.
- **MAI-UI-8B dominates GUI-only easy tasks** — 89% (8/9) on android_easy GUI, beating all other agents including 30B+ models.
- **Claude Opus 4.6 dominates information-retrieval tasks** — 100% (25/25) across all IR difficulties via direct database/file queries.
- **UI-Venus-1.5-30B at 60.3% (32k) vs 59.5% (8k)** — marginal improvement from larger context. GUI-only performance unchanged at 40.0%.
- **GUI-Owl-1.5-32B at 55.2% (default agent)** — competitive with Qwen3-VL (56.0%) but far below the ref-faithful 69.0%. The gap is from wrong seeds, 2-message format, and temperature=0.0.
- **vllm version matters** — MAI-UI-8B drops from 69.8% to 31.0% when served with vllm 0.13 vs 0.11. Always use vllm 0.11.0 with max-model-len 32768 for local model evaluation.

## Run Details

| | GUI-Owl-1.5 (ref)† | Claude Opus 4.6 | Venus-1.5 (32k) | Venus-1.5 (8k) | Qwen3-VL-30B | GUI-Owl-1.5-32B | Terminus2 m2.7 | MAI-UI-8B (0.11) | MAI-UI-8B (0.13) | Gemini 2.5 Pro |
|--|---------------------|-----------------|-----------------|----------------|--------------|-----------------|----------------|------------------|------------------|----------------|
| Date | 2026-04-15 | 2026-04-08 | 2026-04-09 | 2026-04-08 | 2026-04-07 | 2026-04-09 | 2026-04-08 | 2026-04-09 | 2026-04-08 | 2026-04-08 |
| Runner | `run_gui_owl_ref.py` | `run_claude_cli.py` | `run_venus.py` | `run_venus.py` | `run_qwen3vl.py` | `run_gui_owl.py` | `run_terminus2.py` | `run_mai.py` | `run_mai.py` | `run_general_e2e.py` |
| Prompt/Agent | `gui_owl_ref_common` | `clean_optimized` | `VenusNaviAgent` | `VenusNaviAgent` | `Qwen3VLAgentMCP` | `GUIOWL15AgentMCP` | `optimized-v2` | `MAIUINaivigationAgent` | `MAIUINaivigationAgent` | `GeneralE2EAgentMCP` |
| Task data | `val_data_refseed30` | seed=7 | seed=7 | seed=7 | seed=7 | seed=7 | seed=7 | seed=7 | seed=7 | seed=7 |
| Docker image | `2026plusswipe` | `2026` | `2026` | `2026` | `2026` | `2026` | `2026` | `2026` | `2026` | `2026` |
| vLLM version | **0.11.0** | — | **0.11.0** | 0.13.0 | — | **0.11.0** | — | **0.11.0** | 0.13.0 | — |
| Max turns/steps | 50 | 30 | 50 | 30 | 30 | 50 | 30 | 50 | 30 | 30 |
| Avg steps/task | 13.0 | 12.7 | 17.2 | 14.2 | 11.7 | 21.3 | 14.0 | 17.4 | 21.1 | 25.8 |
| Temperature | vLLM default | — | 0.0 | 0.0 | 0.0 | 0.0 | 0.7 | 0.0 | 0.0 | 0.0 |
| Avg time/task | 46s | 91s | 140s | 102s | 135s | 198s | 168s | 214s | 267s | 282s |
| Avg input tokens/task | 146,588 | 325,196 | 58,062 | 47,252 | 42,938 | 84,921 | 288,128 | 161,825 | 191,868 | 75,405 |
| Avg output tokens/task | 632 | 2,799 | 2,045 | 1,618 | 1,381 | 1,106 | 4,107 | 1,773 | 2,079 | 2,667 |
| max-model-len | 32,768 | — | 32,768 | 8,192 | 8,192 | 32,768 | — | 32,768 | 32,768 | — |
| Results dir | `ClaudeCodeCLI_GUIOwl1532BInstruct_260415_0108/` | `ClaudeCodeCLI_claudeopus46_260408_0122/` | `ClaudeCodeCLI_..._Venus_260409_1357/` | `UIVenus15_30BA3B_260408/` | `ClaudeCodeCLI_qwenqwen3vl30ba3binstruct_260407_2117/` | `ClaudeCodeCLI_..._GUIOwl_260409_2305/` | `ClaudeCodeCLI_openrouterminimaxminimaxm27_260408_0207/` | `ClaudeCodeCLI_..._260409_1200/` | `MAIUI8B_260408/` | `ClaudeCodeCLI_googlegemini25pro_260408_*` |

†Ref-faithful runs use `val_data_refseed30.jsonl` (per-task seeds matching reference), `androidworld:2026plusswipe` Docker image (pixel swipe + sleep fixes), and each model's native agent/prompt:
- **GUI-Owl-1.5**: multi-turn + `convert_format()`, `<tool_call>` format, 10× step budget. See [reproduction report](../../docs/design/gui_owl_reproduction_report.md).
- **UI-Venus-1.5**: 2-msg with text history, `<think>/<action>/<conclusion>` format, 10× step budget (50× for 8B extended run).
- **MAI-UI**: multi-turn with 3-image history, `<thinking>/<tool_call>` format, AW app list, 50× step budget. Direction-based swipe benefits most from higher budget (+9 tasks vs 10×).
- **Gemini 3.1 Pro / Qwen3-VL-32B**: GUI-Owl prompt (no native agent available), 10× step budget.

GUI-only task IDs: 0, 1, 8, 20, 28, 29, 30, 37, 40, 47, 55, 75, 76, 78, 80

---

# Tier 4 ADB-Exclusive Task Evaluation Results

Benchmark: `all_tasks_seed7.jsonl` (50 ADB-exclusive tasks, seed=7)
Docker image: `androidworld:2026plusswipe_tier4`

These tasks extend AndroidWorld with 50 tasks specifically designed so that
CLI/ADB agents can solve them efficiently while GUI agents would need
prohibitively many error-prone steps (bulk file ops, database queries,
cross-app data joins, hidden system state inspection).

## Overall

| Agent | Model | Action Space | Prompt | API | Max Turns | Success | Rate | Avg Steps | Avg In Tokens | Avg Out Tokens |
|-------|-------|-------------|--------|-----|----------:|--------:|-----:|----------:|--------------:|---------------:|
| Claude Code CLI | claude-opus-4-6 | ADB shell | `clean_optimized_tools` | Anthropic | 50 | **37/50** | **74.0%** | 16.0 | 333,024 | 3,245 |
| Claude Code CLI | claude-opus-4-6 | ADB shell | `clean_optimized` | Anthropic | 50 | 36/50 | 72.0% | 18.0 | 394,933 | 3,944 |
| Claude Code CLI | claude-sonnet-4 | ADB shell | `clean_optimized_tools` | Anthropic | 50 | 32/50 | 64.0% | 14.2 | 356,139 | 3,502 |
| Claude Code CLI | claude-sonnet-4 | ADB shell | `clean_optimized` | Anthropic | 50 | 29/50 | 58.0% | 14.6 | 364,902 | 3,710 |
| Qwen3-VL-32B | qwen3-vl-32b-instruct | GUI (pixel swipe) | — | OpenRouter | 50 | 16/50 | 32.0% | 12.6 | 47,768 | 1,535 |
| MAI-UI-8B | MAI-UI-8B | GUI (tap/swipe) | — | Local vLLM | 50 | 15/50 | 30.0% | 24.4 | 233,223 | 2,107 |
| UI-Venus-1.5-8B | UI-Venus-1.5-8B | GUI (tap/swipe) | — | Local vLLM | 50 | 8/50 | 16.0% | 5.2 | 16,837 | 504 |

## Per-Task Results (Opus 4.6, 50 turns)

| # | Task | Steps | Result |
|---|------|------:|--------|
| 0 | Tier4BulkDeleteTmpInDownloads | 57 | OK |
| 1 | Tier4CoverageNoTmpInDownloads | 33 | OK |
| 2 | Tier4HiddenStateListAppVersions | 36 | OK |
| 3 | Tier4AggregationCountUnreadSMS | 25 | OK |
| 4 | Tier4CrossAppSmsNumbersNotInContacts | 30 | OK |
| 5 | Tier4BulkRenameScreenshots | 37 | OK |
| 6 | Tier4BulkMoveLargeFiles | 26 | OK |
| 7 | Tier4FilterRecentLogFiles | 19 | OK |
| 8 | Tier4BulkAppendFooterToMarkdown | 41 | OK |
| 9 | Tier4AggregationLongestMarkorNote | 28 | FAIL |
| 10 | Tier4TopKMarkorMostModifiedNotes | 42 | OK |
| 11 | Tier4FilterDeleteOldNonContactKeywordSms | 27 | OK |
| 12 | Tier4TopKSmsThreadsByCount | 51 | FAIL |
| 13 | Tier4CrossAppContactsNoRecentSms | 41 | OK |
| 14 | Tier4FilterContactsBirthdayNoPhone | 59 | OK |
| 15 | Tier4AggregationLongestContactName | 29 | OK |
| 16 | Tier4DedupContactsDuplicatePhones | 43 | OK |
| 17 | Tier4DedupMergeContactsSamePhone | 42 | OK |
| 18 | Tier4BulkRecategorizeExpense | 23 | OK |
| 19 | Tier4FilterExpenseHighTravelLastMonth | 36 | OK |
| 20 | Tier4AggregationExpenseCategoryTop3 | 12 | FAIL |
| 21 | Tier4DedupExpenseSuspectedDuplicates | 37 | OK |
| 22 | Tier4TopKExpenseHighestAmount | 31 | OK |
| 23 | Tier4CrossAppExpenseToMarkorCalendar | 50 | OK |
| 24 | Tier4BulkChangePriorityTasks | 49 | OK |
| 25 | Tier4CoverageOverdueTasksCompleted | 29 | OK |
| 26 | Tier4FilterJoplinContainsNotContains | 40 | OK |
| 27 | Tier4DedupJoplinSameTitleNotes | 40 | OK |
| 28 | Tier4AggregationOpenTracksWeeklyStats | 29 | OK |
| 29 | Tier4TopKOpenTracksFastestActivity | 36 | OK |
| 30 | Tier4CrossAppOpenTracksToTasks | 51 | OK |
| 31 | Tier4FilterRetroMusicMultiCondition | 45 | OK |
| 32 | Tier4TopKRetroMusicLongestSongs | 50 | OK |
| 33 | Tier4CrossAppBroccoliToMarkorIndex | 34 | OK |
| 34 | Tier4CrossAppFilesCreatedDuringEvents | 35 | OK |
| 35 | Tier4CrossAppMarkorPhonesVsContacts | 37 | OK |
| 36 | Tier4AggregationDownloadSizeTop3 | 36 | OK |
| 37 | Tier4TopKLargestDownloadFiles | 35 | OK |
| 38 | Tier4CoverageAllSmsRead | 21 | FAIL |
| 39 | Tier4HiddenStateLocationPermissions | 55 | FAIL |
| 40 | Tier4HiddenStateAudioRouting | 41 | OK |
| 41 | Tier4CoverageAppsCameraPermission | 41 | FAIL |
| 42 | Tier4CoverageWifiConnected | 33 | FAIL |
| 43 | Tier4BulkDeleteCalendarTestEvents | 26 | OK |
| 44 | Tier4CrossAppCalendarToMarkor | 28 | OK |
| 45 | Tier4FilterCalendarLongNoReminder | 52 | OK |
| 46 | Tier4AggregationCalendarTotalDuration | 40 | FAIL |
| 47 | Tier4DedupCalendarDeleteDuplicateEvents | 29 | OK |
| 48 | Tier4TopKCalendarEarliestEvent | 51 | OK |
| 49 | Tier4CoverageCalendarEventsHaveReminders | 51 | FAIL |

## Key Observations

- **CLI agents outperform GUI agents** — Opus 4.6 CLI achieves 74% vs best GUI (Qwen3-VL-32B) at 32%, a 2.3x gap. GUI agents can solve tasks where information is visually accessible (reading counts, browsing lists, editing text), but fail on bulk operations, database queries, system introspection, and cross-app data joins.
- **Specialized tools help** — `clean_optimized_tools` (with sql/read-file/write-file/find-files) consistently outperforms `clean_optimized` (adb only): Opus 74% vs 72%, Sonnet 64% vs 58%. The gain comes from automatic shell escaping in database and file operations.
- **Model capability matters** — Opus 4.6 (74%) vs Sonnet 4 (64%) with the same tools prompt. The gap narrows with tools (was larger without).
- **Remaining hard tasks** — 13 tasks Opus fails include: cross-app joins (contacts+SMS, expense+calendar), coverage checks (permissions, WiFi, SMS read status), and temporal reasoning (calendar duration). These require multi-step schema discovery and precise data manipulation.

## Run Details

| | Opus 4.6 tools | Opus 4.6 | Sonnet 4 tools | Sonnet 4 | Qwen3-VL-32B | MAI-UI-8B | Venus-1.5-8B |
|--|----------------|----------|----------------|----------|--------------|-----------|--------------|
| Date | 2026-04-16 | 2026-04-16 | 2026-04-16 | 2026-04-16 | 2026-04-16 | 2026-04-16 | 2026-04-16 |
| Runner | `run_claude_cli.py` | `run_claude_cli.py` | `run_claude_cli.py` | `run_claude_cli.py` | `run_qwen3vl.py` | `run_mai.py` | `run_venus.py` |
| Prompt/Agent | `clean_optimized_tools` | `clean_optimized` | `clean_optimized_tools` | `clean_optimized` | `Qwen3VLAgentMCP` | `MAIUINaivigationAgent` | `VenusNaviAgent` |
| Docker image | `2026plusswipe_tier4` | `2026plusswipe_tier4` | `2026plusswipe_tier4` | `2026plusswipe_tier4` | `2026plusswipe_tier4` | `2026plusswipe_tier4` | `2026plusswipe_tier4` |
| Max turns | 50 | 50 | 50 | 50 | 50 | 50 | 50 |
| Effort | high | high | high | high | — | — | — |
| vLLM version | — | — | — | — | — | **0.11.0** | **0.11.0** |
| Avg steps/task | 16.0 | 18.0 | 14.2 | 14.6 | 12.6 | 24.4 | 5.2 |
| Avg input tokens/task | 333,024 | 394,933 | 356,139 | 364,902 | 47,768 | 233,223 | 16,837 |
| Avg output tokens/task | 3,245 | 3,944 | 3,502 | 3,710 | 1,535 | 2,107 | 504 |
| Total input tokens | 16,651,189 | 19,746,655 | 17,806,932 | 18,245,096 | 2,388,403 | 11,661,141 | 841,833 |
| Total output tokens | 162,257 | 197,203 | 175,122 | 185,525 | 76,733 | 105,351 | 25,194 |
| Results dir | `..._claudeopus4_260416_1329/` | `..._claudeopus4_260416_1316/` | `..._claudesonnet4_260416_1250/` | `..._claudesonnet4_260416_1301/` | `..._qwen3vl32b_260416_1359/` | `..._MAIUI8B_260416_1451/` | `..._Venus158B_260416_1419/` |

---

# MobileWorld Evaluation Results

Benchmark: `gui_only_tasks.jsonl` (117 GUI-only tasks)

## Overall

| Agent | Model | Action Space | API | SR | Paper SR |
|-------|-------|-------------|-----|---:|--------:|
| Claude Code CLI | claude-opus-4-6 | ADB shell + tools | Anthropic | **45.3%** (53/117) | — |
| Claude Code CLI | claude-sonnet-4-6 | ADB shell + tools | Anthropic | **37.6%** (44/117) | — |
| GeneralE2E | Kimi K2.5 | GUI (tap/swipe) | OpenRouter | **37.6%** (44/117) | 49.6% |
| MAI-UI (vllm 0.11) | MAI-UI-8B | GUI (tap/swipe) | Local vLLM | **21.4%** (25/117) | 27.5% |
| UI-Venus-1.5 | UI-Venus-1.5-30B-A3B | GUI (tap/swipe) | Local vLLM | **11.1%** (13/117) | 17.1% |
| MAI-UI (vllm 0.13) | MAI-UI-8B | GUI (tap/swipe) | Local vLLM | **6.0%** (7/117) | 27.5% |

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

## Per-Category Breakdown (Claude Code CLI)

| Category | Opus 4.6 | Sonnet 4.6 |
|----------|--------:|----------:|
| mastodon (38) | **25/38 (66%)** | 17/38 (45%) |
| other (18) | 7/18 (39%) | 7/18 (39%) |
| mattermost (15) | 3/15 (20%) | 2/15 (13%) |
| files (13) | 4/13 (31%) | **8/13 (62%)** |
| settings (7) | 5/7 (71%) | 5/7 (71%) |
| mall (7) | 0/7 (0%) | 0/7 (0%) |
| email (5) | 2/5 (40%) | 2/5 (40%) |
| calendar/alarm (5) | **3/5 (60%)** | 2/5 (40%) |
| sms/messages (5) | **2/5 (40%)** | 1/5 (20%) |
| map (2) | **2/2 (100%)** | 0/2 (0%) |
| chrome (2) | 0/2 (0%) | 0/2 (0%) |

## Run Details

| | Claude Opus 4.6 | Claude Sonnet 4.6 | Kimi K2.5 | MAI-UI-8B (0.11) | UI-Venus-1.5-30B | MAI-UI-8B (0.13) |
|--|-----------------|-------------------|-----------|------------------|------------------|------------------|
| Date | 2026-04-09 | 2026-04-09 | 2026-04-08 | 2026-04-09 | 2026-04-08 | 2026-04-08 |
| Runner | `run_claude_cli.py` | `run_claude_cli.py` | `run_gui_agent_broker.py` | `run_gui_agent_broker.py` | `run_gui_agent_broker.py` | `run_gui_agent_broker.py` |
| Prompt/Agent | `mw_terminal_expert` | `mw_terminal_expert` | `general_e2e` | `mai_ui_agent` | `ui_venus_agent` | `mai_ui_agent` |
| Action space | ADB shell + tools | ADB shell + tools | GUI (tap/swipe) | GUI (tap/swipe) | GUI (tap/swipe) | GUI (tap/swipe) |
| vLLM version | — | — | — | **0.11.0** | — | 0.13.0 |
| Max turns/steps | 50 | 50 | 50 | 50 | 50 | 50 |
| Avg turns/task | 36.7 | 36.1 | 23.5 | 32.2 | 18.7 | — |
| Temperature | — | — | 0.0 | 0.0 | 0.0 | 0.0 |
| Avg time/task | 194s | 174s | 265s | 278s | 111s | — |
| Avg input tokens/task | 961,919 | 1,021,701 | 290,828 | 297,280 | 24,554 | — |
| Avg output tokens/task | 7,265 | 7,685 | 2,909 | 1,919 | 655 | — |
| Total cost | $95.89 | $60.77 | — | — | — | — |
| max-model-len | — | — | — | 32,768 | 8,192 | 8,192 |
| Results dir | `ClaudeCodeCLI_MW_claudeopus46_260409_2253/` | `ClaudeCodeCLI_MW_claudesonnet46_260409_1602/` | `GUIAgent_general_e2e_moonshotaikimik25_260408_0252/` | `GUIAgent_mai_ui_agent_..._260409_0204/` | `GUIAgent_ui_venus_agent_UIVenus1530BA3B_260408_0157/` | `GUIAgent_mai_ui_agent_..._260408_1155/` |
