# AndroidWorld Evaluation: Claude Code CLI (Opus 4.6) vs UI-TARS-7B-SFT

**Date:** 2026-03-11
**Runs compared:**
- **Claude Code CLI** (`ClaudeCodeCLI_claudeopus46_260310_2350`) -- ADB-only, no screenshots, no a11y tree, 87 terminal tasks
- **UI-TARS-7B-SFT** (`AndroidAgent_UITARS7BSFT_260310_1953`) -- Screenshot-based VLM agent, 116 full tasks (87 terminal + 29 GUI-only)

---

## 1. Overall Success Rates

| Agent | Scope | Solved | Total | SR |
|-------|-------|--------|-------|----|
| Claude Code CLI (Opus 4.6) | Terminal tasks | 46 | 87 | **52.9%** |
| UI-TARS-7B-SFT | Terminal tasks | 20 | 87 | **23.0%** |
| UI-TARS-7B-SFT | All tasks | 29 | 116 | **25.0%** |
| UI-TARS-7B-SFT | GUI-only tasks | 9 | 29 | **31.0%** |

Claude more than doubles UI-TARS's success rate on the overlapping terminal task set. UI-TARS performs slightly better on GUI-only tasks (31.0%) than on terminal tasks (23.0%), but neither is strong.

---

## 2. Per-Task Confusion Matrix (87 terminal tasks)

|  | UITARS Solved | UITARS Failed |
|--|:---:|:---:|
| **Claude Solved** | 14 | 32 |
| **Claude Failed** | 6 | 35 |

- **Both solved:** 14 tasks (16.1%)
- **Only Claude:** 32 tasks (36.8%)
- **Only UITARS:** 6 tasks (6.9%)
- **Neither:** 35 tasks (40.2%)

**Oracle ensemble (union):** 52/87 = **59.8%**, meaning UITARS contributes 6 additional tasks beyond what Claude solves. The complementarity is asymmetric -- Claude provides 32 tasks UITARS misses, but UITARS provides only 6 that Claude misses.

---

## 3. Success Rate by App Category

| Category | N | Claude SR | UITARS SR | Delta |
|----------|---|-----------|-----------|-------|
| Music (Retro Music) | 2 | 2/2 (100%) | 0/2 (0%) | +100% |
| File Manager | 2 | 2/2 (100%) | 0/2 (0%) | +100% |
| Gallery | 1 | 1/1 (100%) | 0/1 (0%) | +100% |
| System Settings | 14 | 11/14 (78.6%) | 8/14 (57.1%) | +21.4% |
| Broccoli | 10 | 7/10 (70.0%) | 4/10 (40.0%) | +30.0% |
| Calendar | 17 | 9/17 (52.9%) | 2/17 (11.8%) | +41.2% |
| OpenTracks | 6 | 3/6 (50.0%) | 0/6 (0%) | +50.0% |
| Joplin | 4 | 2/4 (50.0%) | 0/4 (0%) | +50.0% |
| Contacts | 2 | 1/2 (50.0%) | 2/2 (100%) | -50.0% |
| Markor | 14 | 5/14 (35.7%) | 0/14 (0%) | +35.7% |
| Expense | 7 | 2/7 (28.6%) | 3/7 (42.9%) | -14.3% |
| Tasks App | 6 | 1/6 (16.7%) | 0/6 (0%) | +16.7% |
| SMS | 2 | 0/2 (0%) | 1/2 (50.0%) | -50.0% |

**Key observations:**
- Claude dominates in categories where ADB shell commands and database queries work well: file operations, music playlist creation (via sqlite), calendar (via content providers), Broccoli recipes (via sqlite).
- UITARS outperforms Claude only in Contacts (+50%), Expense (+14.3%), and SMS (+50%) -- categories where GUI interaction may be more reliable than Claude's ADB approach.
- Both agents struggle with Tasks App (Claude 16.7%, UITARS 0%).

---

## 4. Action vs Information Retrieval Tasks (Claude)

| Task Type | Solved | Total | SR |
|-----------|--------|-------|----|
| Action tasks | 36 | 62 | **58.1%** |
| IR (info retrieval) tasks | 10 | 25 | **40.0%** |

Claude performs better on action tasks than information retrieval. For IR tasks, failures are typically due to:
- **Incorrect data extraction** from databases (wrong date ranges, wrong filters)
- **Premature finish signals** ("task was already marked as finished")
- **Close-but-wrong answers** (e.g., "6" tasks due vs the actual count; "1/2 cup" of goji berries vs the expected answer)

---

## 5. By Difficulty Level (Claude)

| Difficulty | Solved | Total | SR |
|------------|--------|-------|----|
| android_easy | 22 | 33 | **66.7%** |
| android_hard | 5 | 9 | **55.6%** |
| android_medium | 9 | 20 | **45.0%** |
| info_easy | 5 | 14 | **35.7%** |
| info_hard | 2 | 3 | **66.7%** |
| info_medium | 3 | 8 | **37.5%** |

Interestingly, Claude handles android_hard better than android_medium, and info_hard better than info_easy/info_medium. The info_easy failures suggest systematic issues with the information retrieval pipeline rather than task complexity.

---

## 6. Failure Mode Analysis

### Claude Code CLI (41 failures)

| Failure Mode | Count | % of Failures |
|--------------|-------|---------------|
| Finished but wrong answer | 34 | 82.9% |
| Hit max turns (~30) | 6 | 14.6% |
| HTTP/runtime error | 1 | 2.4% |

Claude's dominant failure mode is **confidently completing the task with a wrong result** (83%). It rarely runs out of steps. The single error was an HTTP 500 from the container reset endpoint.

Common wrong-answer patterns:
- **Database manipulation errors:** Deleted from sqlite but app didn't reflect changes (Broccoli task 4, Expense tasks). The sqlite-level changes don't always sync with the app's runtime state.
- **Contacts creation:** Created the contact via content provider but the data format was slightly wrong, causing a query error.
- **Brightness minimum:** Set brightness to 0, which was correct numerically, but the verifier expected a different state (task 44).
- **SMS:** Claude cannot interact with SMS apps via ADB commands alone -- sending SMS requires UI interaction or the telephony API which ADB doesn't expose well.
- **Calendar IR tasks:** Queried the calendar database but applied wrong date filters (e.g., wrong "Tuesday" date, wrong week boundaries).

### UI-TARS-7B-SFT (67 failures on terminal tasks)

| Failure Mode | Count | % of Failures |
|--------------|-------|---------------|
| Finished but wrong | 45 | 67.2% |
| Hit max steps | 22 | 32.8% |

UITARS hits max steps more often (33%) than Claude (15%), indicating the 7B model gets stuck in repetitive UI interaction loops. A common pattern is repeatedly clicking the same UI element (e.g., trash icon, menu button) without achieving the desired effect.

---

## 7. Step Count Distribution

| Agent | Task Outcome | Mean Steps | Median | Min | Max |
|-------|-------------|------------|--------|-----|-----|
| Claude | Successful | 8.3 | 7 | 2 | 25 |
| Claude | Failed | 13.2 | 12 | 1 | 33 |
| UITARS | Successful | 7.5 | 7 | 3 | 14 |
| UITARS | Failed | 12.3 | 11 | 3 | 30 |

Both agents show a similar pattern: failed tasks require ~60% more steps than successful ones. The median for successful tasks is 7 steps for both agents, suggesting that solvable tasks have a natural complexity ceiling.

---

## 8. Cost and Efficiency (Claude Code CLI)

| Metric | Value |
|--------|-------|
| **Total cost** | $26.62 |
| **Cost per task** | $0.31 |
| **Cost per successful task** | $0.58 |
| **Successful task avg cost** | $0.22 |
| **Failed task avg cost** | $0.40 |
| **Total input tokens** | 29.0M |
| **Total output tokens** | 245K |
| **Avg input tokens/task** | 333.5K |
| **Avg output tokens/task** | 2.8K |
| **Total wall time** | ~208 min (parallel) |
| **Avg time per task (success)** | 103s |
| **Avg time per task (fail)** | 193s |

The input/output token ratio is ~118:1, meaning the vast majority of cost comes from reading the long system prompt and conversation context, not from generating actions. Failed tasks cost 1.8x more than successful ones due to more turns.

**Top 5 most expensive tasks** (all failures):
1. Task 27 (clipboard copy): $1.00
2. Task 82 (recipes from file): $0.76
3. Task 86 (expenses from file): $0.74
4. Task 48 (add expenses): $0.73
5. Task 68 (cross-app SMS): $0.71

---

## 9. Tasks Only UITARS Solved (6 tasks)

| ID | Task | Claude Failure Reason |
|----|------|-----------------------|
| 4 | Delete recipe: Chicken Caesar Salad Wrap | Claude deleted via sqlite but app didn't sync |
| 9 | Create contact for David Li | Content provider query error after creation |
| 11 | Delete expense: Taxi Fare | Database file path issue |
| 44 | Turn brightness to min | Set to 0 but verifier rejected |
| 49 | Delete duplicate expenses | Incorrect duplicate identification |
| 67 | Send SMS to +15260181590 | ADB can't send SMS through Simple SMS app |

These 6 tasks reveal systematic ADB limitations: app database manipulation doesn't always propagate to the app state, and SMS requires UI-level interaction.

---

## 10. Key Insights

### Claude's Strengths
1. **Database-level operations:** Direct sqlite queries and content provider manipulation give Claude a massive advantage for data-oriented tasks (Calendar, Broccoli, OpenTracks, Joplin, Markor file operations).
2. **System settings:** Simple `svc` and `settings` commands handle wifi, bluetooth, brightness reliably (78.6% SR).
3. **File system operations:** `rm`, `mv`, `cp`, `ls` via ADB shell make file management trivial (100% SR).
4. **Reasoning over structured data:** Claude can query databases, parse results, and reason about them -- giving it an edge on information retrieval tasks that UITARS cannot do at all (0% on OpenTracks, Joplin, Tasks).

### Claude's Weaknesses
1. **App state synchronization:** Modifying sqlite databases directly doesn't always update the app's in-memory state. This caused failures on Broccoli (task 4), Expense (task 11), and Contacts (task 9).
2. **SMS and UI-gated operations:** Some actions (sending SMS through a specific app, certain contact creation flows) require actual UI interaction that ADB commands cannot replicate.
3. **Date/time reasoning:** Calendar IR tasks failed due to wrong date calculations ("this Tuesday", "next week", relative date references).
4. **Premature finish:** Several IR tasks show Claude triggering finish before properly validating its answer.

### UITARS's Strengths
1. **GUI-native operations:** Contacts (100% SR), SMS (50%), and some expense tasks benefit from being able to see and click UI elements.
2. **No app-state sync issues:** Because it interacts through the GUI, changes are always properly reflected.

### UITARS's Weaknesses
1. **Repetitive loops:** The 7B model frequently gets stuck clicking the same element repeatedly (32.8% hit max steps).
2. **Cannot read databases:** Zero success on OpenTracks, Joplin, Tasks App -- all require reading structured data that is invisible in the GUI without navigation.
3. **Low overall capability:** Even on "easy" tasks like Markor note management, UITARS scores 0%.

### Complementarity
An oracle ensemble achieves **59.8%** (52/87), a 6.9pp improvement over Claude alone. The gain comes entirely from UITARS handling 6 GUI-gated tasks. A practical improvement would be to give Claude a fallback to UI-based interaction (screenshots + taps) for tasks where ADB database manipulation fails, particularly for SMS, contacts, and expense apps.
