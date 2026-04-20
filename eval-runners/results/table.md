# AndroidWorld Evaluation Results

Benchmark: `val_data_seed7.jsonl` (116 tasks, seed=7)
Task split: **101 CLI-solvable** | **15 GUI-only** (per [ground truth reference](../../docs/final/AndroidWorld2026/androidworld_ground_truth_reference.md))

## Overall

| Agent | Model | Action Space | API | Overall | CLI (101) | GUI (15) | Cost |
|-------|-------|-------------|-----|--------:|----------:|---------:|-----:|
| Claude Code CLI | claude-opus-4-6 | ADB shell | Anthropic | **63.8%** (74/116) | **71.3%** (72/101) | 13.3% (2/15) | $35.89 |
| UI-Venus-1.5 (32k) | UI-Venus-1.5-30B-A3B | GUI (tap/swipe) | Local vLLM | **60.3%** (70/116) | 63.4% (64/101) | **40.0%** (6/15) | — |
| UI-Venus-1.5 (8k) | UI-Venus-1.5-30B-A3B | GUI (tap/swipe) | Local vLLM | **59.5%** (69/116) | 62.4% (63/101) | **40.0%** (6/15) | — |
| Qwen3VLAgentMCP | qwen3-vl-30b-a3b-instruct | GUI (tap/swipe) | OpenRouter | **56.0%** (65/116) | 58.4% (59/101) | **40.0%** (6/15) | — |
| Terminus2 | minimax-m2.7 | ADB shell | OpenRouter | **52.6%** (61/116) | 58.4% (59/101) | 13.3% (2/15) | $5.82 |
| MAI-UI (vllm 0.11) | MAI-UI-8B | GUI (tap/swipe) | Local vLLM | **69.8%** (81/116) | 72.3% (73/101) | **53.3%** (8/15) | — |
| MAI-UI (vllm 0.13) | MAI-UI-8B | GUI (tap/swipe) | Local vLLM | **31.0%** (36/116) | 33.7% (34/101) | 13.3% (2/15) | — |
| GeneralE2E | gemini-2.5-pro | GUI (tap/swipe) | OpenRouter | **13.8%** (16/116) | 13.9% (14/101) | 13.3% (2/15) | — |

## CLI-Solvable Tasks (101) by Difficulty

| Difficulty | Claude Opus 4.6 | Venus-1.5 (32k) | Venus-1.5 (8k) | Qwen3-VL-30B | Terminus2 m2.7 | MAI-UI-8B (0.11) | MAI-UI-8B (0.13) | Gemini 2.5 Pro |
|------------|----------------:|----------------:|---------------:|-------------:|---------------:|-----------------:|-----------------:|---------------:|
| android_easy (38) | 22/38 (58%) | 30/38 (79%) | 28/38 (74%) | 29/38 (76%) | 23/38 (61%) | **33/38 (87%)** | 16/38 (42%) | 8/38 (21%) |
| android_medium (26) | 18/26 (69%) | 12/26 (46%) | 14/26 (54%) | 10/26 (38%) | 16/26 (62%) | 17/26 (65%) | 6/26 (23%) | 2/26 (8%) |
| android_hard (12) | 7/12 (58%) | 5/12 (42%) | 4/12 (33%) | 5/12 (42%) | 3/12 (25%) | 5/12 (42%) | 1/12 (8%) | 0/12 (0%) |
| info_easy (14) | **14/14 (100%)** | 10/14 (71%) | 10/14 (71%) | 9/14 (64%) | 10/14 (71%) | 12/14 (86%) | 5/14 (36%) | 3/14 (21%) |
| info_medium (8) | **8/8 (100%)** | 6/8 (75%) | 7/8 (88%) | 5/8 (62%) | 4/8 (50%) | 5/8 (62%) | 4/8 (50%) | 1/8 (12%) |
| info_hard (3) | **3/3 (100%)** | 1/3 (33%) | 0/3 (0%) | 1/3 (33%) | 3/3 (100%) | 1/3 (33%) | 2/3 (67%) | 0/3 (0%) |

## GUI-Only Tasks (15) by Difficulty

| Difficulty | Claude Opus 4.6 | Venus-1.5 (32k) | Venus-1.5 (8k) | Qwen3-VL-30B | Terminus2 m2.7 | MAI-UI-8B (0.11) | MAI-UI-8B (0.13) | Gemini 2.5 Pro |
|------------|----------------:|----------------:|---------------:|-------------:|---------------:|-----------------:|-----------------:|---------------:|
| android_easy (9) | 1/9 (11%) | 6/9 (67%) | 5/9 (56%) | 5/9 (56%) | 1/9 (11%) | **8/9 (89%)** | 2/9 (22%) | 2/9 (22%) |
| android_medium (2) | 0/2 (0%) | 0/2 (0%) | 1/2 (50%) | 1/2 (50%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) |
| android_hard (4) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) | 0/4 (0%) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) | 0/4 (0%) |

## Key Observations

- **MAI-UI-8B (vllm 0.11) leads overall at 69.8%** — massive improvement over 31.0% with vllm 0.13. The vllm version critically affects model behavior; **vllm 0.11.0 is required** for correct MAI-UI-8B inference.
- **MAI-UI-8B dominates GUI-only easy tasks** — 89% (8/9) on android_easy GUI, beating all other agents including 30B+ models.
- **Claude Opus 4.6 dominates information-retrieval tasks** — 100% (25/25) across all IR difficulties via direct database/file queries.
- **UI-Venus-1.5-30B at 60.3% (32k) vs 59.5% (8k)** — marginal improvement from larger context. GUI-only performance unchanged at 40.0%.
- **Qwen3-VL and UI-Venus tie on GUI-only tasks** — both at 40.0% (6/15).
- **vllm version matters** — MAI-UI-8B drops from 69.8% to 31.0% when served with vllm 0.13 vs 0.11. Always use vllm 0.11.0 with max-model-len 32768 for local model evaluation.

## Run Details

| | Claude Opus 4.6 | Venus-1.5 (32k) | Venus-1.5 (8k) | Qwen3-VL-30B | Terminus2 m2.7 | MAI-UI-8B (0.11) | MAI-UI-8B (0.13) | Gemini 2.5 Pro |
|--|-----------------|-----------------|----------------|--------------|----------------|------------------|------------------|----------------|
| Date | 2026-04-08 | 2026-04-09 | 2026-04-08 | 2026-04-07 | 2026-04-08 | 2026-04-09 | 2026-04-08 | 2026-04-08 |
| Runner | `run_claude_cli.py` | `run_venus.py` | `run_venus.py` | `run_qwen3vl.py` | `run_terminus2.py` | `run_mai.py` | `run_mai.py` | `run_general_e2e.py` |
| Prompt/Agent | `clean_optimized` | `VenusNaviAgent` | `VenusNaviAgent` | `Qwen3VLAgentMCP` | `optimized-v2` | `MAIUINaivigationAgent` | `MAIUINaivigationAgent` | `GeneralE2EAgentMCP` |
| vLLM version | — | **0.11.0** | 0.13.0 | — | — | **0.11.0** | 0.13.0 | — |
| Max turns/steps | 30 | 50 | 30 | 30 | 30 | 50 | 30 | 30 |
| Avg steps/task | 12.7 | 17.2 | 14.2 | 11.7 | 14.0 | 17.4 | 21.1 | 25.8 |
| Temperature | — | 0.0 | 0.0 | 0.0 | 0.7 | 0.0 | 0.0 | 0.0 |
| Avg time/task | 91s | 140s | 102s | 135s | 168s | 214s | 267s | 282s |
| Avg input tokens/task | 325,196 | 58,062 | 47,252 | 42,938 | 288,128 | 161,825 | 191,868 | 75,405 |
| Avg output tokens/task | 2,799 | 2,045 | 1,618 | 1,381 | 4,107 | 1,773 | 2,079 | 2,667 |
| max-model-len | — | 32,768 | 8,192 | 8,192 | — | 32,768 | 32,768 | — |
| Results dir | `ClaudeCodeCLI_claudeopus46_260408_0122/` | `ClaudeCodeCLI_..._Venus_260409_1357/` | `UIVenus15_30BA3B_260408/` | `ClaudeCodeCLI_qwenqwen3vl30ba3binstruct_260407_2117/` | `ClaudeCodeCLI_openrouterminimaxminimaxm27_260408_0207/` | `ClaudeCodeCLI_..._260409_1200/` | `MAIUI8B_260408/` | `ClaudeCodeCLI_googlegemini25pro_260408_*` |

GUI-only task IDs: 0, 1, 8, 20, 28, 29, 30, 37, 40, 47, 55, 75, 76, 78, 80

---

# MobileWorld Evaluation Results

Benchmark: `gui_only_tasks.jsonl` (117 GUI-only tasks)

## Overall

| Agent | Model | Prompt | Action Space | API | SR | Paper SR |
|-------|-------|--------|-------------|-----|---:|--------:|
| Claude Code CLI | claude-opus-4-7 | `mw_terminal_expert_tier1a_pure` ✓ ⭐ | raw bash (adb/exec/finish only) | Anthropic | **66.7%** (78/117) | — |
| Claude Code CLI | claude-opus-4-7 | `mw_terminal_expert_tier1` ⚠️ | ADB shell + tools | Anthropic | **64.1%** (75/117) | — |
| Claude Code CLI | claude-opus-4-7 | `mw_terminal_expert_tier1a` ✓ | ADB shell + tools | Anthropic | **58.1%** (68/117) | — |
| Claude Code CLI | claude-opus-4-6 | `mw_terminal_expert` (v1) | ADB shell + tools | Anthropic | **45.3%** (53/117) | — |
| Claude Code CLI | claude-opus-4-7 | `mw_terminal_expert_tier1b` (no encyclopedia) | ADB shell + tools | Anthropic | **43.6%** (51/117) | — |
| Claude Code CLI | claude-sonnet-4-6 | `mw_terminal_expert_tier1a` ✓ | ADB shell + tools | Anthropic | **39.3%** (46/117) | — |
| Claude Code CLI | claude-sonnet-4-6 | `mw_terminal_expert` (v1) | ADB shell + tools | Anthropic | **37.6%** (44/117) | — |
| GeneralE2E | Kimi K2.5 | — | GUI (tap/swipe) | OpenRouter | **37.6%** (44/117) | 49.6% |
| MAI-UI (vllm 0.11) | MAI-UI-8B | — | GUI (tap/swipe) | Local vLLM | **21.4%** (25/117) | 27.5% |
| UI-Venus-1.5 | UI-Venus-1.5-30B-A3B | — | GUI (tap/swipe) | Local vLLM | **11.1%** (13/117) | 17.1% |
| MAI-UI (vllm 0.13) | MAI-UI-8B | — | GUI (tap/swipe) | Local vLLM | **6.0%** (7/117) | 27.5% |

> ⚠️ **`tier1` includes benchmark-leaking content** — names specific apps (Mattermost, gmailclone), DBs (`pg mattermost mattermost`), tables/columns the eval queries, and the management CLI `mmctl`. The 64.1% number is **not a clean score**.
>
> ✓ **`tier1a` is leak-free** — same generic discipline (mandatory verification before finish, ban on substituting UI-cache writes for real send mechanisms, subtask checklist) but with all benchmark-specific recipes/app/DB names stripped. **58.1% is the cleanly-defensible improvement.**
>
> Both Tier 1 variants use Opus 4.7, max_turns=50. Generic-prompt-discipline contributes +12.8 pp over the v1 Opus 4.6 baseline; the leaked recipes added a further +6.0 pp on top.
>
> **Tier 1b ablation (Opus 4.7, 43.6%)** — same three discipline rules but stripped of v1's 25-item Android encyclopedia (filesystem layout, content URIs, intent extras, timestamp conventions, etc.). Encyclopedia turns out to be load-bearing: tasks needing standard Android API knowledge (sms / email / files / calendar) regress 14-50 pp without it. Discipline rules alone do NOT compensate. Mastodon and settings tasks are encyclopedia-insensitive (74% / 86% on both).
>
> **Sonnet 4.6 + Tier 1a (39.3%)** — gets only +1.7 pp from Tier 1a vs its own v1 baseline (37.6%), far less than Opus 4.7's +12.8 pp gain from the same prompt. Tier 1a's discipline rules require *follow-through* (decompose subtasks, query verify destinations, retry on verify-fail) and Sonnet executes these less consistently than Opus. Cost-per-success: Sonnet+T1a $1.69, Opus 4.7+T1a $2.29 — Sonnet cheaper per win, but solves 22 fewer tasks.
>
> **Thinking mode**: All Claude rows above use the Claude Code CLI default (no `--effort` flag → no extended thinking budget). Numbers are the no-thinking baseline. Adding `--effort high` is an untested upgrade path.
>
> ⭐ **`tier1a_pure` is the new clean record (66.7%)** — beats both `tier1a` (58.1%) and even the leaky `tier1` (64.1%). Has *only 3 documented bridge commands* (`adb`, `exec`, `finish`), drops v1's 25-item Android encyclopedia, drops the 14-command `mw_tools.py` helpers. The agent composes `adb shell sqlite3 ...`, `exec "docker exec ... psql ..."`, etc. from raw shell. Three discipline rules retained (verify, no-cache-shortcut, subtask checklist) + 3 non-obvious Android patterns (media scanner, corrupt DB, integer ID maps). ~1,400 tokens (vs `tier1a`'s 2,500). Bridge: `mw_env.py` (minimal). Lesson: fewer documented helpers + force-discovery beats more documented helpers + curated knowledge.

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

| Category | Opus 4.6 v1 | Opus 4.7 Tier 1 ⚠️ | Opus 4.7 Tier 1a ✓ | Opus 4.7 Tier 1a pure ⭐ | Opus 4.7 Tier 1b | Sonnet 4.6 Tier 1a ✓ |
|----------|------------:|------------------:|--------------------:|-------------------------:|-----------------:|----------------------:|
| mastodon (38)        | 25/38 (66%) | 30/38 (79%) | 28/38 (74%) | **31/38 (82%)** | 28/38 (74%) | 22/38 (58%) |
| other (25)           | 7/25 (28%)  | 10/25 (40%) | 12/25 (48%) | **13/25 (52%)** | 4/25 (16%) | 5/25 (20%) |
| mattermost (15)      | 3/15 (20%)  | 5/15 (33%)  | 4/15 (27%)  | **8/15 (53%)** | 3/15 (20%) | 2/15 (13%) |
| files (13)           | 4/13 (31%)  | **10/13 (77%)** | 7/13 (54%) | 8/13 (62%) | 4/13 (31%) | 5/13 (38%) |
| settings (7)         | 5/7 (71%)   | **6/7 (86%)** | **6/7 (86%)** | **6/7 (86%)** | **6/7 (86%)** | 4/7 (57%) |
| calendar/alarm (7)   | 4/7 (57%)   | **5/7 (71%)** | **5/7 (71%)** | **5/7 (71%)** | 4/7 (57%) | 3/7 (43%) |
| sms/messages (5)     | 2/5 (40%)   | 3/5 (60%)   | 2/5 (40%)   | **4/5 (80%)** | 1/5 (20%) | 3/5 (60%) |
| email (4)            | 1/4 (25%)   | **4/4 (100%)** | 2/4 (50%) | 1/4 (25%) | 0/4 (0%) | 1/4 (25%) |
| map (2)              | **2/2 (100%)** | **2/2 (100%)** | **2/2 (100%)** | **2/2 (100%)** | 1/2 (50%) | 1/2 (50%) |
| chrome (1)           | 0/1 (0%)    | 0/1 (0%)    | 0/1 (0%)    | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) |
| **TOTAL (117)**      | **53/117 (45.3%)** | **75/117 (64.1%)** | **68/117 (58.1%)** | **78/117 (66.7%)** ⭐ | **51/117 (43.6%)** | **46/117 (39.3%)** |

Notes:
- **Tier 1a pure beats every other variant including the leaky Tier 1.** Removing the 14-command `mw_tools.py` wrapper and the 25-item Android encyclopedia *helped*. Big wins on `mattermost` (+27 pp vs Tier 1a), `sms/messages` (+40 pp), `mastodon` (+8 pp). One regression: `email` (-25 pp). The minimal prompt forces the agent to discover schemas / URIs / app paths fresh per task, which beats canned (potentially stale) prior knowledge.
- **Tier 1 → Tier 1a deltas** show where the leaked app-specific recipes helped most: `email` (4/4 → 2/4) and `files` (10/13 → 7/13). Leakage benefited cross-app email and file tasks where recipes named specific apps/DBs.
- **Tier 1a → Tier 1b deltas** were misleading: the 43.6% drop seemed to indicate "encyclopedia is load-bearing," but `tier1a_pure` (no encyclopedia, no helpers, just discipline + 3 patterns) lands at 66.7%. The actual culprit was Tier 1b retaining 14 documented helper commands as distraction.
- **Sonnet 4.6 + Tier 1a vs Opus 4.7 + Tier 1a** — Sonnet underperforms Opus by 19 pp despite the same prompt. Discipline rules require self-imposed protocols (decompose subtasks, query verify destinations, retry on verify-fail) that Sonnet executes less consistently. Sonnet is 50% cheaper and barely beats its own v1 baseline (37.6% → 39.3%), suggesting Tier 1a's lift is mostly an Opus-only benefit on this task family.

## Run Details

| | Opus 4.7 Tier 1a pure ⭐ | Opus 4.7 Tier 1 ⚠️ | Opus 4.7 Tier 1a ✓ | Opus 4.7 Tier 1b | Sonnet 4.6 Tier 1a ✓ | Opus 4.6 v1 | Sonnet 4.6 v1 | Kimi K2.5 | MAI-UI-8B (0.11) | UI-Venus-1.5-30B | MAI-UI-8B (0.13) |
|--|-------------------------|-------------------|---------------------|------------------|----------------------|-------------|---------------|-----------|------------------|------------------|------------------|
| Date | 2026-04-20 | 2026-04-19 | 2026-04-19 | 2026-04-19 | 2026-04-19 | 2026-04-09 | 2026-04-09 | 2026-04-08 | 2026-04-09 | 2026-04-08 | 2026-04-08 |
| Runner | `run_claude_cli.py` | `run_claude_cli.py` | `run_claude_cli.py` | `run_claude_cli.py` | `run_claude_cli.py` | `run_claude_cli.py` | `run_claude_cli.py` | `run_gui_agent_broker.py` | `run_gui_agent_broker.py` | `run_gui_agent_broker.py` | `run_gui_agent_broker.py` |
| Prompt/Agent | `mw_terminal_expert_tier1a_pure` | `mw_terminal_expert_tier1` | `mw_terminal_expert_tier1a` | `mw_terminal_expert_tier1b` | `mw_terminal_expert_tier1a` | `mw_terminal_expert` | `mw_terminal_expert` | `general_e2e` | `mai_ui_agent` | `ui_venus_agent` | `mai_ui_agent` |
| Action space | raw bash (adb/exec/finish only) | ADB shell + tools | ADB shell + tools | ADB shell + tools | ADB shell + tools | ADB shell + tools | ADB shell + tools | GUI (tap/swipe) | GUI (tap/swipe) | GUI (tap/swipe) | GUI (tap/swipe) |
| Bridge script | `mw_env.py` (minimal) | `mw_tools.py` | `mw_tools.py` | `mw_tools.py` | `mw_tools.py` | `mw_tools.py` | `mw_tools.py` | — | — | — | — |
| Thinking (`--effort`) | — (default) | — (default) | — (default) | — (default) | — (default) | — (default) | — (default) | — | — | — | — |
| vLLM version | — | — | — | — | — | — | — | — | **0.11.0** | — | 0.13.0 |
| Max turns/steps | 50 | 50 | 50 | 50 | 50 | 50 | 50 | 50 | 50 | 50 | 50 |
| Avg input tokens/task | — | 1,371,964 | 1,472,582 | — | — | 961,919 | 1,021,701 | 290,828 | 297,280 | 24,554 | — |
| Avg output tokens/task | — | — | — | — | — | 7,265 | 7,685 | 2,909 | 1,919 | 655 | — |
| Total cost | **$178.73** | **$148.97** | **$155.83** | — | **$77.72** | $95.89 | $60.77 | — | — | — | — |
| Cost per win | $2.29 | $1.99 | $2.29 | — | $1.69 | $1.81 | $1.38 | — | — | — | — |
| max-model-len | — | — | — | — | — | — | — | — | 32,768 | 8,192 | 8,192 |
| Results dir | `ClaudeCodeCLI_MW_claudeopus47_260420_0253_full_tier1a_pure_t50/` | `ClaudeCodeCLI_MW_claudeopus47_260419_0105_full_tier1_t50/` | `ClaudeCodeCLI_MW_claudeopus47_260419_0153_full_tier1a_t50/` | `ClaudeCodeCLI_MW_claudeopus47_260419_1411_sub32_tier1b/` | `ClaudeCodeCLI_MW_claudesonnet46_260419_2120_full_tier1a_t50/` | `ClaudeCodeCLI_MW_claudeopus46_260409_2253/` | `ClaudeCodeCLI_MW_claudesonnet46_260409_1602/` | `GUIAgent_general_e2e_moonshotaikimik25_260408_0252/` | `GUIAgent_mai_ui_agent_..._260409_0204/` | `GUIAgent_ui_venus_agent_UIVenus1530BA3B_260408_0157/` | `GUIAgent_mai_ui_agent_..._260408_1155/` |

### Tier 1 / Tier 1a / Tier 1b Prompt Design

- **`mw_terminal_expert_tier1`** (`eval-runners/agents/cli/claude_sdk/prompts/mw_terminal_expert_tier1.py`) — adds three sections to v1: **mandatory verification before finish**, **forbidden shortcuts** (no `state.json` / UI-cache writes), **subtask checklist on turn 1**. Includes specific verification recipes naming Mattermost DBs, gmailclone Postgres, mmctl. **⚠️ Contains benchmark-leakage; use only for ceiling estimates.**
- **`mw_terminal_expert_tier1a`** (`eval-runners/agents/cli/claude_sdk/prompts/mw_terminal_expert_tier1a.py`) — same three sections but **all benchmark-specific app/DB/CLI/file names removed**. The agent must discover apps and tables via `find-files` / `pg ... "\dt"` / `sql ... ".tables"`. Inherits v1's 25-item Android encyclopedia. **✓ Cleanly defensible improvement.**
- **`mw_terminal_expert_tier1b`** (`eval-runners/agents/cli/claude_sdk/prompts/mw_terminal_expert_tier1b.py`) — minimalist build (`clean_optimized` philosophy + the three discipline rules), stripped of v1's Android encyclopedia but **kept all 14 `mw_tools.py` helper commands documented**. Result: 43.6%, below v1 baseline. Initially attributed to "encyclopedia is load-bearing"; `tier1a_pure` later showed the actual culprit was the 14 documented helpers being distracting.
- **`mw_terminal_expert_tier1a_pure`** (`eval-runners/agents/cli/claude_sdk/prompts/mw_terminal_expert_tier1a_pure.py`) — **⭐ best clean variant (66.7%)**. Documents only 3 bridge commands (`adb`, `exec`, `finish`), no `mw_tools.py` helpers, no v1 encyclopedia. Agent composes raw `adb shell sqlite3 ...`, `exec "docker exec ... psql ..."`, etc. Bridge: `mw_env.py` (minimal). Carries the three Tier 1 generic discipline rules + 3 non-obvious Android patterns from `clean_optimized`. ~1,400 tokens. Beats every other variant including the leaky `tier1` (64.1%).
- The Tier 1a → Tier 1 delta (+6.0 pp) quantifies how much the leaked recipes contribute on top of generic discipline.
- The Tier 1a → Tier 1a pure delta (**+8.6 pp**) shows that *removing* documented helpers and the encyclopedia improves SR — the agent makes better decisions when forced to discover schemas/URIs/paths fresh per task.
