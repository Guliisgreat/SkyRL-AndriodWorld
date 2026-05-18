# Tier 4 Dataset Specification — 45-Task ADB-Exclusive Benchmark

**Purpose.** This document is the canonical reference for the **Tier-4
45-task realistic subset** of the AndroidWorld benchmark used in the
*CLI-vs-GUI agent paradigm comparison* paper. It supersedes the design draft
in `docs/design/tier4_final.md` (56-task scope) and pairs with the operational
ground-truth reference in `tier4_ground_truth_reference_v2.md`. Read this
when:

- you are a teammate ramping onto the benchmark or its eval pipeline;
- you are Claude Code being asked to extend, evaluate, or write about it;
- you are writing the paper and need precise dataset claims (counts,
  categories, exclusion criteria, reward semantics, baselines).

The audience is engineers and researchers, not end users — the doc is dense
and assumes familiarity with Android, SQLite, ADB, and standard ML eval.

---

## 1. Research question

> Is there a class of mobile tasks where an agent that drives the device
> through **`adb shell`** has a *structural* advantage over an agent that
> drives it through **screenshots and clicks** (the GUI paradigm) — and how
> large is that advantage in practice?

Tier 4 is the dataset we use to answer this. Every task is hand-selected so
that **a CLI agent can reduce it to one or a few shell/SQL commands**, while
the GUI paradigm has to scroll through paginated screens, open one item at a
time, or read state the OS doesn't surface in any visible UI.

Tier 4 is intentionally a *worst-case* benchmark for GUI agents — the goal
is to characterize the upper bound on CLI advantage, not to make a balanced
comparison.

---

## 2. Dataset summary

| field | value |
|---|---|
| total tasks | **45** |
| categories | 5 (B / C / A / D / E) |
| seeds | 3 (`{7, 30, 1234}`) — every task can be regenerated under any seed |
| environment image | `androidworld:2026plusswipe_tier4` (Android 13 / API 33 emulator, toybox 0.8.6) |
| container endpoint | HTTP server with `/reset`, `/step_adb`, `/health` (Pythonic harness) |
| step budget per task | 50 turns (`max_turns=50`) |
| temperature | 0.0 |
| reproducer | `docker/androidworld_2026plusswipe_tier4/test_integration.py` — golden-path solvers pass 45/45 |
| ground-truth reference | `docs/final/cli_advantage/tier4_ground_truth_reference_v2.md` |
| data files | `eval-runners/data/tier4/realistic_subset_seed{7,30,1234}.jsonl` (one row per task) |
| canonical eval doc | `docs/final/cli_advantage/three_agent_eval_45tasks_3seeds.md` (6-agent baselines) |

### 2.1 Category breakdown

| cat | label | count | task IDs |
|---|---|---|---|
| **B** | Bulk / Dedup | 10 | 0, 3, 4, 5, 13, 19, 32, 34, 46, 49 |
| **C** | Filter / Coverage | 10 | 9, 10, 20, 23, 35, 42, 43, 45, 47, 50 |
| **A** | Aggregation / TopK | 10 | 7, 8, 11, 15, 16, 17, 21, 22, 24, 28 |
| **D** | CrossApp | 9 | 18, 25, 26, 33, 51, 52, 53, 54, 55 |
| **E** | Hidden State | 6 | 29, 31, 36, 37, 38, 39 |
| | **Total** | **45** | |

The task-ID space is sparse (0-55 with gaps) because the IDs are inherited
from the original 56-task design — see §3 for which IDs were dropped.

---

## 3. From 56 to 45 — exclusion rationale

The original `docs/design/tier4_final.md` specified 56 tasks across the same
5 categories. The 11-task delta was removed when we found, during ground-
truth verification, that they either misrepresent the CLI-advantage thesis
or are unsolvable on the production fixture for reasons that have nothing to
do with the agent. Excluded tasks:

| id | task | reason |
|---|---|---|
| 1 | HiddenStateListAppVersions | unusual ask — hardcoded list of 3 specific apps |
| 2 | CrossAppSmsNumbersNotInContacts | fixture uses telnet `text_emulator` which does not land in `mmssms.db` on this AVD |
| 6 | AggregationLongestMarkorNote | unusual phrasing — "char count" instead of "longest" |
| 12 | DedupMergeContactsSamePhone | unusual merge rule — "alphabetically first" not "most complete info" |
| 14 | FilterExpenseHighTravelLastMonth | needs last-month date filter; AVD clock frozen Oct 2023 vs fixture host time May 2026 |
| 27 | AggregationDownloadSizeTop3 | unusual phrasing — "total size in bytes" |
| 30 | HiddenStateAudioRouting | combined ask (routing device AND volume in one) |
| 40 | HiddenStateSignalStrength | power-user phrasing — "signal strength in dBm" |
| 41 | HiddenStateSmsDbSize | implementation-level — "SMS database storage size" |
| 44 | FilterLargeOldFiles | needs `-mtime +30` against device clock; same skew as 14 |
| 48 | AggregationExpenseAllCategorized | dev/admin framing — "verify all are categorized" |

The two exclusion patterns are:

1. **Phrasing is unrealistic for a human user.** A human asks *"which note
   has the most content?"*, not *"which note has the highest char count?"*.
   These tasks would unfairly disadvantage agents that match goal text to
   queries by surface form.
2. **Environment bug.** The AVD clock is frozen at Oct 2023 (cold-boot
   snapshot) while fixtures seed timestamps from the host clock at runtime
   (May 2026). Tasks that rely on a date predicate (e.g. `-mtime +30`,
   `WHERE dueDate < strftime('%s','now')`) become trivially unsolvable
   because the cutoff is ~2.5 years before any seeded row. This is an
   environment issue, not a benchmark difficulty signal.

For paper claims, the 45-task subset is the eval-set; the 11-task delta is
documented but not measured.

---

## 4. Category specifications

Each category encodes a specific *kind* of CLI advantage. The shape of the
task — what the agent must do — flows from the category.

### 4.1 B — Bulk / Dedup (10 tasks)

**Hypothesis.** Many independent items need to change in one stroke
(rename, delete, update, move).

- **CLI advantage.** One `find … -delete`, one `UPDATE … WHERE …`, one
  `for f in *; do mv "$f" …; done`. Atomic from the agent's perspective.
- **GUI cost.** Long-press, multi-select, scroll, repeat. Some app UIs
  don't even expose multi-select for the target field (e.g. recategorize
  expense entries).
- **Eval shape.** *State-check*: post-action device state is compared to
  the expected state. The agent's output text is mostly ignored; what
  matters is whether the right rows were updated / files deleted.

### 4.2 C — Filter / Coverage (10 tasks)

**Hypothesis.** Find the subset of items satisfying a conjunction of
conditions, or verify that all items satisfy a property.

- **CLI advantage.** `WHERE … AND …`, `SELECT … WHERE NOT EXISTS …`,
  set-difference via `comm` / Python.
- **GUI cost.** UI filters are usually one-dimensional; multi-condition
  requires repeated manual passes and external state tracking.
- **Eval shape.** *Cache-match*: ground truth is the canonical answer
  (e.g. list of contact names); reward = 1 iff agent's `FINISH(content=…)`
  payload contains the expected substrings.

### 4.3 A — Aggregation / TopK (10 tasks)

**Hypothesis.** Compute a sum, count, mean, top-K, or duplicate report
over all rows.

- **CLI advantage.** SQL `GROUP BY ... ORDER BY ... LIMIT`, or shell
  `sort -rn | head -k`. O(rows) work in one round-trip.
- **GUI cost.** Read each row, accumulate state externally.
- **Eval shape.** *Cache-match*. Top-K answers must contain the expected
  item names; aggregate answers must contain the numeric value.

### 4.4 D — CrossApp (9 tasks)

**Hypothesis.** Read state from one app, transform, write to another (or
compare two apps' state).

- **CLI advantage.** Read source (SQLite or content provider), pipe to a
  one-shot script, write destination (file or `content insert`). Joins
  across apps that share no common UI surface.
- **GUI cost.** App-switching while remembering source state; manual
  cross-referencing.
- **Eval shape.** *Hybrid*: checks both the device-state mutation (target
  file/row was created) and the agent's reported summary text.

### 4.5 E — Hidden State (6 tasks)

**Hypothesis.** Query device state that no app exposes — kernel
counters, permission grants, install-time metadata, telemetry.

- **CLI advantage.** `dumpsys <component>`, `/proc/<X>`, `pm list
  permissions`, `appops`.
- **GUI cost.** Often *impossible* — the data isn't in any UI surface.
- **Eval shape.** *Cache-match* — the FINISH payload must include the
  specific value(s) the goal asks for.

---

## 5. Per-task data contract

Every task is implemented as a Python class in
`docker/android/skyrl_server/tier4/<file>.py` (one file per app/domain).
Each class follows the AndroidWorld task interface (subclass of
`task_eval.TaskEval`) and contributes a row in
`docker/android/skyrl_server/registry_ext.py` at a positional index that
matches its `task_id`.

A task spec consists of:

| field | type | source | purpose |
|---|---|---|---|
| `task_id` | int | registry index | stable identifier across seeds |
| `task_name` | str | class name | e.g. `Tier4BulkRecategorizeExpense` |
| `category` | str | one of `{A, B, C, D, E}` | drives the eval shape |
| `seed` | int | JSONL row | randomization basis (see §6) |
| `task` | str | goal template | natural-language instruction to the agent |
| `initialize_task(env)` | method | task class | resets app state; seeds fixture data |
| `is_successful(env)` | method | task class | returns float reward (0.0 or 1.0) |
| ground-truth oracle | section in v2 doc | `docs/final/cli_advantage/tier4_ground_truth_reference_v2.md` | reference D/I/P/A commands |

The JSONL row carried into the runner has this exact shape (example for
seed=7, task_id=0):

```json
{
  "task_id": 0,
  "task_name": "Tier4BulkDeleteTmpInDownloads",
  "seed": 7,
  "task": "Delete all .tmp files in the Downloads folder.",
  "difficulty": "tier4",
  "category": "adb_exclusive"
}
```

Note: the JSONL's `category` field is the legacy AndroidWorld tag (always
`adb_exclusive` for Tier-4 rows); the per-task **paradigm** category
(A/B/C/D/E) lives on the task class itself, accessed via
`GoldenPath.category` in `test_integration.py`. The paper should cite the
A/B/C/D/E label, not the JSONL `category` field.

---

## 6. Seeds and randomization

- Every task fixture is seeded by `random.Random(seed)` (or NumPy
  equivalent) inside `initialize_task(env)`. The same `(task_id, seed)`
  always reproduces the same on-device state.
- Three reference seeds are published: **7, 30, 1234**. These are the
  evaluation seeds for paper results. Use these — don't pick fresh seeds
  unless adding a new ablation.
- What changes seed-to-seed:
  - Concrete data values (SMS bodies, contact phone numbers, file
    sizes, expense amounts/dates, calendar event titles).
  - Concrete substring fillers in goal text (the keyword in *"events
    containing 'X'"* changes per seed).
  - The expected `FINISH` payload for cache-match tasks.
- What is **stable across seeds**:
  - Task ID, class name, category label.
  - Goal sentence template, eval logic, golden-path solver structure.

This means a single task class generalizes across seeds — agents must
solve the problem class, not memorize values.

### 6.1 The three published JSONL files

```
eval-runners/data/tier4/realistic_subset_seed7.jsonl     # 45 rows
eval-runners/data/tier4/realistic_subset_seed30.jsonl    # 45 rows
eval-runners/data/tier4/realistic_subset_seed1234.jsonl  # 45 rows
```

They are derived by filtering `all_tasks_seed{7,30,1234}.jsonl` (the full
56-row tier-4 sets) to the 45 IDs in §2.1.

---

## 7. Evaluation patterns

Three reward shapes, picked per task by its category:

### 7.1 State-check (B + write-side D)

```python
def is_successful(self, env) -> float:
    rows = adb_utils.issue_generic_request(
        "shell", "sqlite3 ... 'SELECT … FROM … WHERE …'", env)
    return 1.0 if matches_expected(rows) else 0.0
```

The eval re-reads device state and compares to the post-action expectation.
The agent's natural-language output is ignored — the grader only cares
whether the right rows changed. Used by: 0, 3, 4, 5, 13, 19, 32, 34, 46,
49 (all of B), plus write-side D tasks (18, 33, 51, 52, 53, 54, 55).

### 7.2 Cache-match (A, C, read-side E)

```python
def is_successful(self, env) -> float:
    return 1.0 if all(s in env.interaction_cache for s in self._expected) else 0.0
```

The grader inspects the agent's `FINISH(content=…)` text. Every expected
substring (computed in `initialize_task` from the seed) must appear.
Substring containment, case-sensitive, no whitespace normalization. Used
by: all 10 of A, all 10 of C, all 6 of E.

### 7.3 Hybrid (cross-app write that also reports)

Both 7.1 and 7.2 must pass. Used by Task 18
(`CrossAppExpenseToMarkorCalendar`) and similar tasks that both *do*
something on the device and *report* a summary.

### 7.4 Determinism guarantees

- `is_successful` is **deterministic** given `(task_id, seed, final
  device state, final cache)`. There is no LLM-judge in the loop.
- The grader never makes network calls.
- For state-check tasks, the grader uses the same canonical query the
  golden-path solver uses (so the test ground-truth and the eval ground-
  truth come from the same code path, eliminating divergence).

---

## 8. Environment & toolchain

### 8.1 Docker image

| property | value |
|---|---|
| image tag | `androidworld:2026plusswipe_tier4` |
| Android version | 13 (API 33) |
| AVD type | userdebug (`adb shell` gets shell uid 2000 + MEDIA_RW group) |
| coreutils | toybox 0.8.6 (Android stock) — supports `stat -c %Y`, `date -d @ts`, `find -printf` |
| sqlite3 | in-image |
| device clock | **frozen at Oct 2023** (cold-boot snapshot — not host time) |
| pre-installed apps | Markor, Pro Expense, OpenTracks, RetroMusic, Joplin, Tasks (org.tasks), Broccoli, Simple Calendar Pro, Telephony provider, Contacts provider |

### 8.2 Pool broker (parallel eval)

For parallel evaluation, spin up the pool broker:

```
python eval-runners/common/runtime/pool_broker.py \
    --pool-size 8 \
    --docker-image androidworld:2026plusswipe_tier4 \
    --port 9501 --base-env-id 800 --parallel 4
```

Runners pass `--broker-url http://localhost:9501 --pool-size 8`. The broker
warms 8 containers, calls `/reset` on `/return`, and tolerates the env-id
counter drifting upward as unhealthy containers get replaced.

### 8.3 Single container (sequential / debug)

A long-lived smoke container can be used directly via `--container-url
http://localhost:5800` for debugging single tasks (see
`test_integration.py`'s `_smoke()` helper).

---

## 9. Known environment caveats

These shape the dataset and how to interpret results.

### 9.1 AVD clock skew

The emulator clock is **Oct 2023** but fixtures seed data from the host
clock at run time (currently May 2026). Three patterns to be aware of when
adding tasks:

- **Compute the window on the host** (Python `datetime.date.today()`),
  then bind it as a literal in the SQL — fixtures use host time, so the
  predicate aligns. Used by Task 52.
- **Clock-independent predicate** (extract `weekday` from a `dtstart`,
  or use a wide enough window that the device-side cutoff is earlier
  than every seeded row). Coincidentally correct because all seeded rows
  are in the device's future. Used by Task 21, 50.
- **Workaround required** when the canonical predicate is device-clock-
  bound and yields the wrong set. Task 19 uses `title LIKE
  'overdue_task_%'` instead of `dueDate < strftime('%s','now')*1000`
  because the latter matches nothing on the frozen clock.

When *adding* a new task, **prefer the first pattern**. Avoid device-side
`strftime('now')` predicates with tight windows.

### 9.2 Toybox quirks

toybox supports GNU-style flags for `stat -c %Y`, `date -d @<ts>`, and
`find -printf "%s %f\n"` — these all work. But:

- `mv`, `cp` over the `/storage/emulated/0/` FUSE mount **don't update
  MediaStore** automatically. If a task's eval queries MediaStore (e.g.
  audio/media URIs), trigger a re-scan via
  `am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d
  file:///storage/...` after writing.
- Avoid `for f in $(find …)` if filenames may contain spaces. Fixtures
  use space-free names today, but new tasks should prefer
  `find … -exec <cmd> {} \;`.

### 9.3 `adb shell` quoting

`adb shell` concatenates everything after `shell` with single spaces, no
re-quoting. The convention used in v2 ground-truth and in
`test_integration.py`:

- Bare form: `adb shell <single-token-cmd>` (e.g. `adb shell dumpsys
  battery`).
- Scripts with spaces / globs / pipes:
  `adb shell "sh -c '<script-with-escaped-doubles>'"`.
  Inside the outer `"…"`, escape `$ → \$`, `` ` → \` ``, `\ → \\`,
  `" → \"`. The inner `'…'` then arrives on the device intact.

This is the form the agent should learn / generate.

---

## 10. Reference implementation

| component | location | role |
|---|---|---|
| Task classes | `docker/android/skyrl_server/tier4/*.py` (one file per app) | `initialize_task`, `is_successful` |
| Registry | `docker/android/skyrl_server/registry_ext.py` (positional tuple `_TIER4_TASKS`) | maps `task_id` → class |
| Golden-path solvers | `docker/androidworld_2026plusswipe_tier4/test_integration.py` (`GOLDEN_PATHS` tuple of `GoldenPath` dataclass) | end-to-end verified oracle CLI for every task; passes 45/45 |
| Ground-truth ref | `docs/final/cli_advantage/tier4_ground_truth_reference_v2.md` | human-readable D/I/P/A walkthrough per task |
| Eval data | `eval-runners/data/tier4/realistic_subset_seed{7,30,1234}.jsonl` | one row per (task, seed) |
| Eval runners | `eval-runners/benchmarks/androidworld/run_claude_cli.py` (CLI agents) · `eval-runners/benchmarks/mobileworld/run_qwen3vl.py` / `run_mai.py` / `run_gui_owl_ref.py` (GUI agents) | drive the agent loop |
| Pool broker | `eval-runners/common/runtime/pool_broker.py` | shared container pool |
| Results | `eval-runners/results/<AgentClass>_<ModelShort>_<yymmdd_HHMM>/` | `results.jsonl`, `summary.json`, `atif_trajectories/` |

The golden-path solvers serve as the **reference implementation of
oracle-CLI behavior**. They are the gold-standard upper bound for what is
achievable on every task. Smoke test: 45/45 pass.

---

## 11. Per-task index

(Categories from §2.1. State-mutation tasks marked **MUT**; others are
cache-match.)

| id | name | cat | eval |
|---|---|---|---|
| 0 | Tier4BulkDeleteTmpInDownloads | B | MUT |
| 3 | Tier4BulkRenameScreenshots | B | MUT |
| 4 | Tier4BulkMoveLargeFiles | B | MUT |
| 5 | Tier4BulkAppendFooterToMarkdown | B | MUT |
| 7 | Tier4TopKMarkorMostModifiedNotes | A | cache |
| 8 | Tier4TopKSmsThreadsByCount | A | cache |
| 9 | Tier4FilterContactsBirthdayNoPhone | C | cache |
| 10 | Tier4FilterContactsNoFamilyName | C | cache |
| 11 | Tier4AggregationContactsDuplicatePhones | A | cache |
| 13 | Tier4BulkRecategorizeExpense | B | MUT |
| 15 | Tier4AggregationExpenseCategoryTop3 | A | cache |
| 16 | Tier4AggregationExpenseSuspectedDuplicates | A | cache |
| 17 | Tier4TopKExpenseHighestAmount | A | cache |
| 18 | Tier4CrossAppExpenseToMarkorCalendar | D | hybrid (MUT + cache) |
| 19 | Tier4BulkChangePriorityTasks | B | MUT |
| 20 | Tier4FilterJoplinContainsNotContains | C | cache |
| 21 | Tier4AggregationOpenTracksWeeklyStats | A | cache |
| 22 | Tier4TopKOpenTracksFastestActivity | A | cache |
| 23 | Tier4FilterRetroMusicMultiCondition | C | cache |
| 24 | Tier4TopKRetroMusicLongestSongs | A | cache |
| 25 | Tier4CrossAppBroccoliToMarkorIndex | D | hybrid |
| 26 | Tier4CrossAppMarkorPhonesVsContacts | D | hybrid |
| 28 | Tier4TopKLargestDownloadFiles | A | cache |
| 29 | Tier4HiddenStateLocationPermissions | E | cache |
| 31 | Tier4HiddenStateAppsCameraPermission | E | cache |
| 32 | Tier4BulkDeleteCalendarTestEvents | B | MUT |
| 33 | Tier4CrossAppCalendarToMarkor | D | hybrid |
| 34 | Tier4DedupCalendarDeleteDuplicateEvents | B | MUT |
| 35 | Tier4CoverageCalendarEventsHaveReminders | C | cache |
| 36 | Tier4HiddenStatePhoneTemperature | E | cache |
| 37 | Tier4HiddenStateRecentInstalls | E | cache |
| 38 | Tier4HiddenStateUptime | E | cache |
| 39 | Tier4HiddenStateBackgroundLocationApps | E | cache |
| 42 | Tier4FilterSmsContainingUrl | C | cache |
| 43 | Tier4CoverageSmsAllFromKnownContacts | C | cache |
| 45 | Tier4FilterEmptyFilesInDownloads | C | cache |
| 46 | Tier4BulkDeleteApkFiles | B | MUT |
| 47 | Tier4FilterExpenseAboveAverage | C | cache |
| 49 | Tier4BulkDeleteSmallExpenses | B | MUT |
| 50 | Tier4FilterCalendarWeekendEvents | C | cache |
| 51 | Tier4CrossAppContactsToMarkor | D | hybrid |
| 52 | Tier4CrossAppCalendarSmsConflicts | D | hybrid |
| 53 | Tier4CrossAppSmsKeywordToTasks | D | hybrid |
| 54 | Tier4CrossAppOpenTracksToMarkor | D | hybrid |
| 55 | Tier4CrossAppJoplinToCalendar | D | hybrid |

---

## 12. Published baselines

From `docs/final/cli_advantage/three_agent_eval_45tasks_3seeds.md` —
mean ± std SR across seeds {7, 30, 1234}:

| agent | paradigm | mean SR | cost (3 seeds) |
|---|---|---|---|
| Claude Code CLI (Opus 4.7) | CLI / ADB | **68.9 % ± 0.0 %** | $56.72 |
| mini-swe-agent + minimax-m2.7 | CLI / ADB | 66.7 % ± 4.4 % | $2.43 |
| Terminus2 + gpt-5.3-codex | CLI / ADB | 60.7 % ± 6.4 % | $9.87 |
| GUI-Owl-1.5-32B | GUI vision | 33.3 % ± 3.8 % | $0 (local) |
| MAI-UI-8B | GUI vision | 27.4 % ± 6.4 % | $0 (local) |
| Qwen3-VL-32B | GUI vision | 22.2 % ± 4.4 % | $0 (free OpenRouter) |
| **golden-path oracle CLI** | reference | **100 % (45/45)** | n/a |

**Headline number for paper:** CLI agents lead GUI agents by **27-47 pp**
in mean SR. The largest gaps are in Filter / Coverage (C) and Aggregation
(A); the smallest gap is in Bulk / Dedup (B). CrossApp (D) caps GUI agents
at ≤ 11 %, regardless of vision-model size.

**Three tasks no agent solves at any seed** (the capability frontier):
`18, 29, 33` — two CrossApp (write-after-read) and one
location-permissions enumeration.

---

## 13. How to extend the benchmark

### 13.1 Adding a task

1. Pick a category that matches the task's *kind of CLI advantage* (§4).
2. Add a new class in the right `docker/android/skyrl_server/tier4/<app>.py`:
   - implement `initialize_task(self, env)` — seeds fixture data using
     `random.Random(self.seed)` and writes to the device via
     `adb_utils.issue_generic_request` or direct sqlite3.
   - implement `is_successful(self, env)` — re-read state (state-check) or
     check `env.interaction_cache` (cache-match). The expected value is
     stored as an instance attribute during `initialize_task`.
3. Append the class to `_TIER4_TASKS` in
   `docker/android/skyrl_server/registry_ext.py` at the right positional
   index (the index becomes `task_id`).
4. Add a `GoldenPath(task_id=…, category=…, commands=(…))` or
   `solver=<fn>` row in `test_integration.py`'s `GOLDEN_PATHS`. Verify the
   golden path achieves reward = 1 against a live container.
5. Add the task to all three JSONL files
   `eval-runners/data/tier4/realistic_subset_seed{7,30,1234}.jsonl`.
6. Add the D/I/P/A walkthrough to
   `docs/final/cli_advantage/tier4_ground_truth_reference_v2.md` (via the
   generator script under `failure_analysis/_tools/` if it still exists,
   else by direct edit).
7. Re-run the smoke (`test_integration.py`) — must stay at 45+1/45+1.

### 13.2 Adding an agent

For paper-grade reporting, an agent should report **all three seeds** on
**all 45 tasks** at the same step budget (50 turns / steps). Use:

- CLI agent: `eval-runners/benchmarks/androidworld/run_claude_cli.py`
  (or the terminus2/mini-swe variants in the same dir).
- GUI agent: `eval-runners/benchmarks/mobileworld/run_qwen3vl.py` /
  `run_mai.py` / `run_gui_owl_ref.py`.

The output dir is named `{AgentClass}_{ModelShort}_{yymmdd}_{HHMM}` per
the convention in `CLAUDE.md`.

After all three seeds finish, append the agent's row to the comparison
doc in `docs/final/cli_advantage/three_agent_eval_45tasks_3seeds.md`
(every table) along with the source-data row.

### 13.3 Running the full eval

```bash
# 1. Start broker
python eval-runners/common/runtime/pool_broker.py \
    --pool-size 8 --docker-image androidworld:2026plusswipe_tier4 \
    --port 9501 --base-env-id 800 --parallel 4

# 2. (Wait for pool_initializing=False — ~5 min for 8 containers)

# 3. Run the agent against each seed
for seed in 7 30 1234; do
  python eval-runners/benchmarks/androidworld/run_claude_cli.py \
    --data eval-runners/data/tier4/realistic_subset_seed${seed}.jsonl \
    --broker-url http://localhost:9501 --pool-size 8 \
    --model claude-opus-4-7 --max-turns 50 \
    --prompt clean_optimized_v10
done

# 4. Compute mean ± std (see scripts in docs/final/cli_advantage/)
```

---

## 14. Paper-writing notes

When citing this dataset in a paper:

- **Name**: *Tier-4 ADB-Exclusive 45-Task Subset* (or *Tier-4 Realistic
  Subset*) — distinct from the original 56-task design draft.
- **Cite for size / categories**: this spec (§2.1) is the source of truth.
  Don't cite `tier4_final.md` directly — it describes the larger 56-task
  draft, not the eval set.
- **Cite for ground truth / reproducibility**:
  `tier4_ground_truth_reference_v2.md` and `test_integration.py`. The
  latter is the canonical reproducer.
- **Cite for baselines**: `three_agent_eval_45tasks_3seeds.md` (currently
  6 agents). Include the three seeds, the step budget, and the temperature
  (0.0) in the paper's eval methodology section.
- **Headline framing**: position Tier-4 as a *worst-case for GUI agents*
  benchmark — not a balanced one. The point is to measure the size of the
  CLI advantage, not to claim GUI agents are uniformly worse.
- **Reward semantics**: state-check vs cache-match vs hybrid (§7).
  Mention this explicitly — readers will assume LLM-judged eval otherwise.
- **What "no agent solves" means**: tasks 18, 29, 33 fail at every seed
  for every agent we tested (6 agents × 3 seeds = 18 runs each). This is
  the capability frontier, not a benchmark artifact.

---

## 15. Open questions / future work

- **Scale beyond 45**: which excluded tasks (§3) can be rehabilitated by
  fixing the AVD clock skew or rephrasing the goal? Tasks 14, 44 (date
  filters) would re-enter the C/B categories if the AVD clock were a
  param.
- **Multilingual goals**: every goal is English; non-English variants
  would test whether agents over-fit to surface text.
- **Counter-tier**: a Tier-5 dataset where GUI agents have a structural
  advantage (visual layout reasoning, accessibility tree exploration)
  would balance the comparison.
- **Reward strictness**: cache-match uses substring containment, which
  is lenient. Stricter matching (exact set, ordered list, JSON parse)
  might separate agents better but would inflate false negatives.

---

## 16. References

- `docs/design/tier4_final.md` — original 56-task design draft (superseded).
- `docs/final/cli_advantage/tier4_ground_truth_reference_v2.md` —
  operational ground-truth, command-by-command.
- `docs/final/cli_advantage/three_agent_eval_45tasks_3seeds.md` —
  current 6-agent baselines.
- `docker/androidworld_2026plusswipe_tier4/test_integration.py` —
  canonical reproducer (45/45 golden-path PASS).
- `docker/android/skyrl_server/registry_ext.py` — task registry.
- `eval-runners/data/tier4/realistic_subset_seed{7,30,1234}.jsonl` —
  eval JSONL.
