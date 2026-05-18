# CLI vs GUI agents on Tier-4 ADB-exclusive tasks

How three CLI-driven agents (Claude Code CLI with Opus 4.7, Terminus2 with
gpt-5.3-codex, mini-swe-agent with minimax-m2.7) stack up against three GUI
vision agents (GUI-Owl-1.5-32B, MAI-UI-8B, Qwen3-VL-32B) on the 45-task
realistic subset of the Tier-4 AndroidWorld benchmark, run across three
random seeds.

---

## Setup

| field | value |
|---|---|
| dataset | `eval-runners/data/tier4/realistic_subset_seed{7,30,1234}.jsonl` |
| tasks | 45 (filtered from the 56-task Tier-4 set; 11 excluded for unrealistic phrasing or AVD-clock skew — see `docs/final/AndroidWorld2026/tier4_ground_truth_reference_v2.md`) |
| categories | B (Bulk / Dedup, 10) · C (Filter / Coverage, 10) · A (Aggregation / TopK, 10) · D (CrossApp, 9) · E (Hidden State, 6) |
| seeds | {7, 30, 1234} |
| environment | `androidworld:2026plusswipe_tier4` Android API 33 emulator, pool broker on port 9501, 8 parallel workers |
| max-steps / max-turns | 50 |
| temperature | 0.0 |
| reproducer | `docker/androidworld_2026plusswipe_tier4/test_integration.py` (golden-path baseline 45/45) |

### Agents

| agent | paradigm | model | API | prompt variant |
|---|---|---|---|---|
| **Claude Code CLI (Opus 4.7)** | ADB shell on a Linux host that talks to the emulator | `claude-opus-4-7` | Anthropic | `clean_optimized_v10` |
| **Terminus2 + gpt-5.3-codex** | ADB shell on a Linux host (XML-action harness) | `openai/gpt-5.3-codex` (reasoning=medium) | OpenAI | `optimized-v6-bash-only` |
| **mini-swe-agent + m2.7** | ADB shell on a Linux host (mini-swe v2.2.8 self-verification) | `openrouter/minimax/minimax-m2.7` | OpenRouter | `v6-bash-only` |
| **GUI-Owl-1.5-32B** | GUI vision agent — screenshot in, click/swipe out (Mobile-Agent-v3.5 paradigm) | `/shared/models/GUI-Owl-1.5-32B-Instruct` | local vLLM (TP=2, port 8402, fp16) | `gui_owl_1_5_ref` |
| **Qwen3-VL-32B (instruct)** | GUI vision agent — screenshot in, click/swipe out | `qwen/qwen3-vl-32b-instruct` | OpenRouter | `qwen3vl_gui` |
| **MAI-UI-8B** | GUI vision agent — screenshot in, click/swipe out | `/shared/models/MAI-UI-8B` | local vLLM (TP=1, port 8401) | `mai_ui_gui` |

---

## Headline result

| agent | seed=7 | seed=30 | seed=1234 | **mean ± std** | cost (3 seeds) |
|---|---|---|---|---|---|
| Claude Code CLI (Opus 4.7) | 31 / 45 (68.9 %) | 31 / 45 (68.9 %) | 31 / 45 (68.9 %) | **68.9 % ± 0.0 %** | $56.72 |
| mini-swe-agent + m2.7 | 28 / 45 (62.2 %) | 32 / 45 (71.1 %) | 30 / 45 (66.7 %) | **66.7 % ± 4.4 %** | $2.43 |
| Terminus2 + gpt-5.3-codex | 29 / 45 (64.4 %) | 29 / 45 (64.4 %) | 24 / 45 (53.3 %) | **60.7 % ± 6.4 %** | $9.87 |
| GUI-Owl-1.5-32B | 17 / 45 (37.8 %) | 14 / 45 (31.1 %) | 14 / 45 (31.1 %) | **33.3 % ± 3.8 %** | $0 (local) |
| MAI-UI-8B | 14 / 45 (31.1 %) | 14 / 45 (31.1 %) | 9 / 45 (20.0 %) | **27.4 % ± 6.4 %** | $0 (local) |
| Qwen3-VL-32B | 10 / 45 (22.2 %) | 12 / 45 (26.7 %) | 8 / 45 (17.8 %) | **22.2 % ± 4.4 %** | $0 (free OpenRouter) |

All three CLI agents lead all GUI agents by ≥27 pp in mean SR. Opus is the
most reliable (zero seed variance) but ~23× more expensive than mini-swe +
m2.7, which lands within 2 pp of Opus at the lowest cost of any priced agent
($2.43 / 3 seeds). Terminus2 + codex trails by another 6 pp at 4× the cost
of mini-swe. Among GUI agents, **GUI-Owl-1.5-32B** is the strongest (33.3 %
mean) — +5.9 pp over MAI-UI-8B and +11.1 pp over the same-size Qwen3-VL-32B,
showing UI-specific instruction tuning matters more than scale alone.

---

## Per-category success rate (mean ± std across 3 seeds)

| category | label | Claude CLI (Opus 4.7) | mini-swe + m2.7 | Terminus2 + codex | GUI-Owl-32B | MAI-UI-8B | Qwen3-VL-32B |
|---|---|---|---|---|---|---|---|
| B | Bulk / Dedup | **76.7 % ± 5.8 %** | 73.3 % ± 11.5 % | 76.7 % ± 5.8 % | 46.7 % ± 5.8 % | 56.7 % ± 5.8 % | 33.3 % ± 5.8 % |
| C | Filter / Coverage | **86.7 % ± 5.8 %** | 76.7 % ± 5.8 % | 56.7 % ± 5.8 % | 40.0 % ± 10.0 % | 36.7 % ± 15.3 % | 20.0 % ± 10.0 % |
| A | Aggregation / TopK | **83.3 % ± 5.8 %** | 80.0 % ± 0.0 % | 83.3 % ± 5.8 % | 43.3 % ± 5.8 % | 10.0 % ± 10.0 % | 36.7 % ± 5.8 % |
| D | CrossApp | 40.7 % ± 6.4 % | **48.1 % ± 12.8 %** | 25.9 % ± 12.8 % | 11.1 % ± 0.0 % | 11.1 % ± 0.0 % | 0.0 % ± 0.0 % |
| E | Hidden State | 44.4 % ± 9.6 % | 44.4 % ± 9.6 % | **55.6 % ± 9.6 %** | 16.7 % ± 16.7 % | 16.7 % ± 0.0 % | 16.7 % ± 0.0 % |
| **all** | **45-task subset** | **68.9 % ± 0.0 %** | 66.7 % ± 4.4 % | 60.7 % ± 6.4 % | 33.3 % ± 3.8 % | 27.4 % ± 6.4 % | 22.2 % ± 4.4 % |

Reading the table:
- All three CLI agents lead all categories. Opus tops 3 (B, C, A); mini-swe + m2.7 tops CrossApp (D); codex tops Hidden State (E).
- **CrossApp (D)** is the hardest category for every agent, but mini-swe is the standout — 48.1 % vs Opus's 40.7 % and codex's 25.9 %. The "verify-by-reading-back" mini-swe loop seems to help on multi-app write-then-read flows.
- **Filter / Coverage (C)** is where the CLI agents diverge most — Opus 87 % vs mini-swe 77 % vs codex 57 %. The 30-pp Opus-vs-codex gap concentrates on Coverage tasks (e.g. *confirm all events have a reminder*) where codex tends to return early without a full scan.
- **Hidden State (E)** has zero variance for MAI and Qwen — they consistently solve 1 / 6 the same way every seed, suggesting a capability ceiling. GUI-Owl shows 16.7 % seed-variance here (1 task flips), the only GUI agent with any E-stochasticity.
- MAI is **stronger than Qwen on file ops (B 56.7 % vs 33.3 %)** but **weaker on aggregation (A 10.0 % vs 36.7 %)**. MAI's UI-grounding focus pays off when the task is "open Files app, select these, delete" — but doesn't translate to multi-step reasoning over numerical fields.
- **GUI-Owl-32B beats both other GUI agents on Aggregation (A 43.3 % vs MAI 10.0 % and Qwen 36.7 %)** and on Filter / Coverage (C 40.0 % vs 36.7 % / 20.0 %). UI-specific training (Mobile-Agent-v3.5) translates directly to those multi-step UI reasoning categories.
- **CrossApp (D)** is the universal blind spot for GUI: 11 % for GUI-Owl and MAI, 0 % for Qwen. The 8B-vs-32B size gap doesn't move D — keeping multi-app state in working memory across screenshots is the bottleneck.

---

## Average steps per category

| category | Claude CLI | mini-swe + m2.7 | Terminus2 + codex | GUI-Owl-32B | MAI-UI-8B | Qwen3-VL-32B |
|---|---|---|---|---|---|---|
| B | 14.2 ± 2.4 | 15.5 ± 1.8 | 4.7 ± 0.4 | 25.7 ± 2.7 | 21.9 ± 1.1 | 22.3 ± 3.2 |
| C | 4.6 ± 1.1 | 9.9 ± 1.4 | 4.3 ± 0.2 | 13.4 ± 2.2 | 19.1 ± 5.5 | 6.7 ± 0.7 |
| A | 10.7 ± 1.2 | 11.8 ± 1.7 | 6.0 ± 1.0 | 12.4 ± 0.2 | 25.1 ± 2.0 | 6.7 ± 1.7 |
| D | 17.6 ± 3.4 | 20.4 ± 0.8 | 9.6 ± 1.2 | 27.4 ± 7.4 | 26.8 ± 1.8 | 12.1 ± 4.1 |
| E | 6.9 ± 2.5 | 22.9 ± 1.7 | 3.1 ± 0.6 | 18.5 ± 3.8 | 25.1 ± 2.6 | 19.3 ± 4.6 |
| **all** | 11.0 ± 1.4 | 15.4 ± 1.2 | **5.7 ± 0.4** | 19.4 ± 1.0 | 23.4 ± 1.6 | 12.9 ± 1.1 |

Terminus2 + codex is the most step-efficient agent overall — ~2× faster than
Opus (5.7 vs 11.0 steps), ~3× faster than mini-swe + m2.7 (15.4), ~4× faster
than MAI. mini-swe + m2.7 is the slowest CLI agent because its
self-verification loop re-reads state after every action; codex tends to
issue one big `find`/SQL command and exit. Among GUI agents, GUI-Owl-32B
(19.4) is between Qwen (12.9, fast but less successful) and MAI (23.4,
thrashes longest).

### Steps split by outcome (mean ± std across 3 seeds)

| category | Claude CLI PASS / FAIL | mini-swe + m2.7 PASS / FAIL | Terminus2 + codex PASS / FAIL | GUI-Owl-32B PASS / FAIL | MAI-UI PASS / FAIL | Qwen-32B PASS / FAIL |
|---|---|---|---|---|---|---|
| B | 11.0 ± 1.7 / 24.6 ± 8.8 | 11.7 ± 2.8 / 27.1 ± 4.4 | 3.7 ± 0.2 / 8.1 ± 1.8 | 13.9 ± 3.0 / 35.4 ± 4.8 | 17.0 ± 3.3 / 27.9 ± 3.6 | 13.2 ± 3.0 / 26.6 ± 5.0 |
| C | 5.2 ± 0.8 / 0.7 ± 1.2 | 7.3 ± 1.8 / 17.9 ± 3.4 | 3.8 ± 0.4 / 5.0 ± 0.2 | 12.6 ± 3.0 / 14.3 ± 2.8 | 11.7 ± 1.1 / 23.9 ± 9.3 | 8.6 ± 1.7 / 6.3 ± 1.3 |
| A | 6.3 ± 0.6 / 36.5 ± 17.8 | 7.3 ± 1.7 / 30.2 ± 1.8 | 4.7 ± 1.2 / 13.2 ± 3.8 | 9.3 ± 1.4 / 14.7 ± 0.8 | 11.5 ± 10.6 / 26.3 ± 2.9 | 5.8 ± 0.9 / 7.3 ± 2.7 |
| D | 10.1 ± 3.1 / 22.4 ± 4.3 | 16.2 ± 2.3 / 24.7 ± 2.0 | 7.3 ± 1.2 / 10.4 ± 1.6 | 19.0 ± 3.0 / 28.5 ± 8.6 | 11.7 ± 1.2 / 28.7 ± 2.1 | — / 12.1 ± 4.1 |
| E | 9.4 ± 2.5 / 5.0 ± 2.4 | 3.2 ± 2.9 / 39.6 ± 4.8 | 1.9 ± 0.8 / 4.3 ± 1.6 | 9.8 ± 1.1 / 21.0 ± 6.9 | 6.3 ± 0.6 / 28.8 ± 3.0 | 19.0 ± 20.8 / 19.3 ± 2.4 |

Notable patterns:
- **Claude CLI C-failures are abandoned at step 0.7** — when it can't form the query, it returns an empty answer immediately.
- **Claude CLI A-failures are stuck loops** — 36.5 steps on average, the highest of any cell. The agent over-explores SQL aggregations.
- **Terminus2 + codex bails early on every failure** — the largest fail-step average is 13.2 (Aggregation), all others under 11. This is a direct consequence of `reasoning_effort=medium` keeping the agent concise.
- **mini-swe + m2.7 hits the 50-step cap on Hidden State and Aggregation failures** (39.6 and 30.2 avg) — its self-verification loop keeps issuing commands until the budget runs out.
- **MAI-UI fails by exhausting the 50-step cap** in 4 of 5 categories (24-29 steps avg).
- **Qwen-32B C-failures are also near-immediate** (6 steps) — like CLI, it gives up rather than burning steps.

---

## Robustness across seeds

For each agent: how many tasks pass on at least one seed (Union) vs all three seeds (Intersection)?

| agent | Union (≥ 1 seed) | Intersection (3 / 3 seeds) | overall mean |
|---|---|---|---|
| Claude CLI (Opus 4.7) | 36 / 45 (80 %) | **26 / 45 (58 %)** | 68.9 % |
| mini-swe-agent + m2.7 | 35 / 45 (78 %) | 25 / 45 (56 %) | 66.7 % |
| Terminus2 + codex | 30 / 45 (67 %) | 24 / 45 (53 %) | 60.7 % |
| GUI-Owl-1.5-32B | 22 / 45 (49 %) | 8 / 45 (18 %) | 33.3 % |
| MAI-UI-8B | 16 / 45 (36 %) | 8 / 45 (18 %) | 27.4 % |
| Qwen3-VL-32B | 13 / 45 (29 %) | 7 / 45 (16 %) | 22.2 % |

The Intersection figure is the right metric for production reliability — these
are tasks the agent solves regardless of fixture randomization.

---

## Tasks no agent solves at any seed

Three tasks fail under every agent at every seed (the GUI-Owl run does not
unlock any new tasks beyond the previous 5-agent set). These represent the
genuine capability frontier — every agent and every paradigm is blocked.

| id | category | task_name | notes |
|---|---|---|---|
| 18 | D | Tier4CrossAppExpenseToMarkorCalendar | requires SUM(expense) → write Markor note → insert calendar event in one flow |
| 29 | E | Tier4HiddenStateLocationPermissions | needs to walk `dumpsys package permissions` for every package; long parse |
| 33 | D | Tier4CrossAppCalendarToMarkor | query calendar + write a Markor file named from goal keyword |

All 3 remaining unsolved tasks combine multi-source correlation with
formatted output. **Newly solved tasks** that were previously in the
"no agent solves" list:

| id | newly solved by | seeds | notes |
|---|---|---|---|
| 19 | mini-swe + m2.7 | 30, 1234 | Bulk priority change on org.tasks — self-verification loop confirms the change took |
| 36 | Terminus2 + codex (3/3), mini-swe + m2.7 (30, 1234) | — | `dumpsys battery` with 1/10 °C unit conversion |
| 51 | mini-swe + m2.7 | 7 | Tier4CrossAppContactsToMarkor — flaky (only 1/3 seeds) but no longer unanimous-fail |

---

## Always-pass tasks per agent

| agent | always-pass count | task IDs |
|---|---|---|
| Claude CLI (Opus 4.7) | 26 | 0, 3, 4, 5, 7, 8, 16, 17, 20, 21, 22, 23, 24, 28, 34, 35, 38, 39, 42, 45, 46, 47, 49, 50, 52, 53 |
| mini-swe-agent + m2.7 | 25 | 0, 3, 4, 5, 7, 8, 9, 10, 11, 16, 17, 20, 21, 22, 26, 28, 37, 38, 42, 43, 45, 46, 47, 49, 52 |
| Terminus2 + codex | 24 | 3, 4, 5, 7, 8, 9, 10, 11, 16, 17, 22, 24, 26, 28, 32, 34, 36, 37, 38, 42, 43, 46, 47, 49 |
| GUI-Owl-1.5-32B | 8 | 0, 4, 10, 15, 20, 46, 47, 49 |
| MAI-UI-8B | 8 | 0, 4, 9, 13, 38, 46, 49, 54 |
| Qwen3-VL-32B | 7 | 0, 15, 17, 20, 22, 46, 49 |

Two tasks pass for every agent under every seed (46, 49) — the "easy floor":
delete .apk files in Downloads, delete small expenses. (Task 0 is the
previous "always-pass for all" but Terminus2 + codex fails it on one seed.)

---

## Always-fail tasks per agent

| agent | always-fail count | task IDs |
|---|---|---|
| Claude CLI (Opus 4.7) | 9 | 15, 18, 19, 29, 31, 33, 36, 51, 54 |
| mini-swe-agent + m2.7 | 10 | 13, 15, 18, 24, 29, 31, 32, 33, 39, 50 |
| Terminus2 + codex | 15 | 13, 15, 18, 19, 20, 23, 29, 33, 35, 39, 50, 51, 52, 53, 54 |
| GUI-Owl-1.5-32B | 23 | 3, 8, 18, 19, 21, 24, 25, 28, 29, 32, 33, 34, 35, 36, 37, 39, 42, 43, 45, 50, 52, 54, 55 |
| MAI-UI-8B | 29 | 3, 7, 8, 11, 15, 17, 18, 19, 21, 22, 25, 26, 28, 29, 31, 32, 33, 34, 35, 36, 37, 39, 42, 43, 50, 51, 52, 53, 55 |
| Qwen3-VL-32B | 32 | 3, 4, 8, 9, 11, 13, 16, 18, 19, 21, 23, 24, 25, 26, 28, 29, 32, 33, 34, 35, 36, 37, 39, 42, 43, 45, 50, 51, 52, 53, 54, 55 |

The CLI agents have the smallest always-fail sets; all three GUI agents fail
on 23-32 of 45 tasks consistently. GUI-Owl-32B's set (23) is meaningfully
smaller than MAI's (29) and Qwen's (32) — UI-tuned 32B closes about a third
of the gap between the smaller MAI and a same-size general VLM. The three
CLI agents share 4 always-fail tasks (15, 18, 29, 33). Both Qwen3-VL-32B
and GUI-Owl-1.5-32B solve **task 15** consistently while every CLI agent
misses — the only "GUI-solves-but-CLI-doesn't" example in the 45-task
subset. The remaining three (18, 29, 33) are the universal capability
frontier.

---

## Source data

| agent / seed | results dir | summary |
|---|---|---|
| Claude CLI / 7 | `eval-runners/results/ClaudeCodeCLI_claudeopus47_260515_2212/` | 31 / 45 |
| Claude CLI / 30 | `eval-runners/results/ClaudeCodeCLI_claudeopus47_260517_0217/` | 31 / 45 |
| Claude CLI / 1234 | `eval-runners/results/ClaudeCodeCLI_claudeopus47_260517_0236/` | 31 / 45 |
| mini-swe + m2.7 / 7 | `eval-runners/results/MiniSweAgent_openrouterminimaxminimaxm27_260517_1341/` | 28 / 45 |
| mini-swe + m2.7 / 30 | `eval-runners/results/MiniSweAgent_openrouterminimaxminimaxm27_260517_2028/` | 32 / 45 |
| mini-swe + m2.7 / 1234 | `eval-runners/results/MiniSweAgent_openrouterminimaxminimaxm27_260517_2036/` | 30 / 45 |
| Terminus2 + codex / 7 | `eval-runners/results/Terminus2_openaigpt53codex_260517_1454/` | 29 / 45 |
| Terminus2 + codex / 30 | `eval-runners/results/Terminus2_openaigpt53codex_260517_1527/` | 29 / 45 |
| Terminus2 + codex / 1234 | `eval-runners/results/Terminus2_openaigpt53codex_260517_1540/` | 24 / 45 |
| GUI-Owl-1.5-32B / 7 | `eval-runners/results/ClaudeCodeCLI_sharedmodelsGUIOwl1532BInstruct_260517_2031/` | 17 / 45 |
| GUI-Owl-1.5-32B / 30 | `eval-runners/results/ClaudeCodeCLI_sharedmodelsGUIOwl1532BInstruct_260517_2118/` | 14 / 45 |
| GUI-Owl-1.5-32B / 1234 | `eval-runners/results/ClaudeCodeCLI_sharedmodelsGUIOwl1532BInstruct_260517_2159/` | 14 / 45 |
| MAI-UI-8B / 7 | `eval-runners/results/ClaudeCodeCLI_sharedmodelsMAIUI8B_260517_0358/` | 14 / 45 |
| MAI-UI-8B / 30 | `eval-runners/results/ClaudeCodeCLI_sharedmodelsMAIUI8B_260517_0425/` | 14 / 45 |
| MAI-UI-8B / 1234 | `eval-runners/results/ClaudeCodeCLI_sharedmodelsMAIUI8B_260517_0451/` | 9 / 45 |
| Qwen3-VL-32B / 7 | `eval-runners/results/ClaudeCodeCLI_qwenqwen3vl32binstruct_260517_0303/` | 10 / 45 |
| Qwen3-VL-32B / 30 | `eval-runners/results/ClaudeCodeCLI_qwenqwen3vl32binstruct_260517_0325/` | 12 / 45 |
| Qwen3-VL-32B / 1234 | `eval-runners/results/ClaudeCodeCLI_qwenqwen3vl32binstruct_260517_0338/` | 8 / 45 |

Each run dir contains `results.jsonl` (one row per task), `summary.json`
(aggregate), `prompt_variant.txt`, and `atif_trajectories/` (per-task action
traces).

---

## Takeaways

1. **CLI agents have a 27–47-pp advantage** in mean SR on Tier-4 ADB-exclusive tasks because the tasks reduce to SQL/shell commands once the agent knows where to look. The GUI paradigm forces an unnecessary detour through the UI for data the system stores in flat files and content providers. All three CLI agents — Opus 4.7 (68.9 %), mini-swe-agent + m2.7 (66.7 %), Terminus2 + codex (60.7 %) — sit well above the best GUI agent (GUI-Owl 33.3 %).
2. **The advantage is largest on data-heavy categories** (C +47 pp for Opus vs GUI-Owl, A +40 pp). For pure UI-ops (B), the gap narrows to 20 pp — MAI-UI-8B closes ~60 % of the gap here.
3. **GUI agents have ≤11 % CrossApp completion** at any seed, regardless of size (8B vs 32B). The bottleneck is keeping multi-app state in working memory across screenshots, not vision quality. The 32B-vs-8B size gap (Qwen vs MAI vs GUI-Owl) shows up on Aggregation but disappears on CrossApp.
4. **GUI tuning beats raw scale**: GUI-Owl-1.5-32B (33.3 %) beats same-size general Qwen3-VL-32B (22.2 %) by 11.1 pp, and 4× larger GUI-Owl beats 8B MAI by only 5.9 pp — UI-specific instruction tuning matters more than the 4× parameter count between MAI and GUI-Owl.
5. **All three GUI agents share the same CrossApp / Hidden-State ceiling** — D is structural (multi-app state) and E often needs string-parsing dumpsys output which screenshot+click can't easily express.
6. **Cost / step efficiency / reliability tradeoff between CLI agents** — Opus is the most reliable (zero seed variance, smallest always-fail set) but ~23× more expensive than mini-swe + m2.7 ($56.72 vs $2.43). Codex is the most step-efficient (5.7 steps avg) and edges Opus on Hidden-State (E). mini-swe + m2.7 lands within 2 pp of Opus at the best $/SR ratio, and is the only agent to top CrossApp (D, 48.1 %).
7. **The 3 tasks no agent solves at any seed** are 2 / 3 CrossApp (18, 33) plus location-permissions enumeration (29). Down from 6 in the original 3-agent evaluation; mini-swe + m2.7 broke tasks 19 and 51, codex broke task 36. GUI-Owl does not unlock new tasks.
8. **CLI agents are complementary** — only 4 tasks (15, 18, 29, 33) are always-fail for all three CLI agents. An ensemble that picks the best result across Opus / mini-swe / codex would in principle solve 41 / 45.
