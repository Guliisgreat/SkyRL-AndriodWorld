# Android-Lab Unified Verifier Refactor

**Date:** 2026-03-27
**Status:** Proposed
**Goal:** Enable fair GUI vs Terminal agent comparison on Android-Lab by unifying the verification system.

---

## 1. Motivation

We want to compare GUI agents and Terminal agents on both AndroidWorld and Android-Lab benchmarks. AndroidWorld's infrastructure is mature — single verifier, shared broker, fair comparison. Android-Lab currently has **two independent verification systems** that produce different results, making fair comparison impossible.

```
AndroidWorld (mature)                 AndroidLab (current — fragmented)
├── Single verifier ✓                 ├── XML verifier (original)
├── Shared broker ✓                   ├── ADB verifier (new, terminal-only)
├── GUI + Terminal use same eval ✓    ├── GUI uses XML, Terminal uses ADB ✗
└── Fair comparison ✓                 └── Cannot compare fairly ✗
```

---

## 2. Background

### 2.1 Original Android-Lab Verification (XML-based)

Located in `Android-Lab/evaluation/tasks/*/`. Each task has a Python class with a `judge(xml_compressed_tree, line)` method that:

1. Dumps UI hierarchy via `uiautomator dump`
2. Parses XML tree into compressed format
3. Searches for expected text/state in the UI tree
4. Returns `{"complete": bool, "1": bool, "2": bool, ...}`

**Pros:** Faithful to original benchmark.
**Cons:** Requires agent to be on the exact right UI page. Fragile string matching on rendered UI. Unusable for terminal agents.

### 2.2 ADB Rule-Based Verification (new)

Located in `skyrl-agent/examples/run_androidlab/verifiers/`. Each task has a Python class with an `is_successful()` method that:

1. Queries device state directly via ADB (`settings get`, `content query`, `sqlite3`, `dumpsys`)
2. Checks whether the task's goal was achieved regardless of UI state
3. Returns same format: `{"complete": bool, "1": bool, ...}`

**Pros:** Agent-agnostic (works for GUI + Terminal). Checks actual device state. Robust to UI navigation.
**Cons:** Not yet validated against original benchmark. One known bug fix in `base.py` (base64 encoding for sqlite3 queries).

### 2.3 Codebase Relationship

```
Android-Lab/                              (Original benchmark)
├── evaluation/config/*.yaml              ← 138 task definitions (source of truth)
├── evaluation/tasks/*/*.py               ← XML verifiers (93 operation + judge for 45 query)
├── eval.py                               ← Runner using XML verifiers
└── agent/                                ← GUI agents (LLM + MLLM)

skyrl-agent/examples/run_androidlab/      (Our adaptation)
├── androidlab_tasks.jsonl                ← Converted from YAML (one-time, embedded)
├── verifiers/                            ← ADB verifiers (independent, no imports from Android-Lab/)
├── run_gui_agent_androidlab.py           ← Standalone GUI agent (no Android-Lab/ imports)
├── run_claude_cli_androidlab.py          ← Terminal agent runner
├── ground_truth_commands.py              ← Ground truth CLI commands for 112 tasks
└── cross_validate_dual.py               ← ONLY file that imports from Android-Lab/
```

The two codebases are **independent** except `cross_validate_dual.py` which imports from `Android-Lab/evaluation/` for cross-validation purposes.

---

## 3. Current Verification Coverage

### 3.1 Task Counts

| Category | Count |
|----------|-------|
| Total tasks | 138 (93 operation + 45 query) |
| All have XML verifiers | 138/138 |
| All have ADB verifiers | 138/138 |
| CLI ground truth commands | 100 pure CLI + 2 GUI + 10 answer-only |
| Verified passing (CLI) | ~98 stable (+ ~2 intermittent timing) |
| GUI-only excluded for terminal | 26 (Calendar 14, Zoom 5, Map ops 5, PiMusic sort 2) |

### 3.2 Per-App Status

| App | Total | ADB Verifier | CLI Ground Truth | Notes |
|-----|-------|-------------|-----------------|-------|
| Settings | 23 | 23 ✓ | 23 ✓ (100%) | All via `settings get/put` |
| Clock | 27 | 27 ✓ | 25 ✓ (93%) | 2 unsolvable: timer, SharedPrefs |
| Contacts | 15 | 15 ✓ | 15 ✓ (100%) | Content provider + BASE64_SH |
| Bluecoins | 15 | 15 ✓ | 15 ✓ (100%) | sqlite3 on `.fydb` |
| Cantook | 12 | 12 ✓ | 12 ✓ (100%) | sqlite3 + WAL checkpoint |
| PiMusic | 12 | 12 ✓ | 8 ✓ (67%) | 2 need GUI tap, 2 unsolvable |
| Map.me | 15 | 15 ✓ | 10 answer-only | Ops need GUI, queries need routing engine |
| Calendar | 14 | 14 ✓ | 0 | Realm DB — no CLI access without Java toolchain |
| Zoom | 5 | 5 ✓ | 0 | Ephemeral UI forms, no local storage |

---

## 4. Refactor Plan

### Step 1: Cross-Validate Verifiers

**Goal:** Prove ADB verifiers agree with XML verifiers on GUI agent trajectories.

**Method:**
1. Run the GUI agent (GPT-4o XML-only) on all 138 tasks using `run_gui_agent_androidlab.py`
2. After each task, evaluate with **both** verifiers on the same container state:
   - XML verifier: dump UI tree, run original `judge()` method
   - ADB verifier: run `is_successful()` method
3. Produce concordance table

**Expected outcomes:**

| Agreement | Count | Action |
|-----------|-------|--------|
| Both PASS | ~30-35 | ✓ Verifiers agree |
| Both FAIL | ~90-95 | ✓ Verifiers agree |
| XML PASS, ADB FAIL | 0-5 | Fix ADB verifier (too strict) |
| XML FAIL, ADB PASS | 0-5 | Fix ADB verifier (too loose) |

**Acceptance criteria:** >95% agreement across all 138 tasks. Any disagreement must be investigated and resolved (by fixing ADB verifier to match XML behavior).

**Important finding from initial testing (2026-03-27):** Cross-validation MUST use the **GUI agent**, not ground truth CLI commands. The XML verifier checks UI page state — if the agent didn't navigate to the right page, XML returns False even if the task was completed. Terminal ground truth commands change device state without navigating UI, so they always get XML=False, ADB=True. This is expected behavior, not a bug.

**Script:** Use `cross_validate_verifiers.py` with a GUI agent run:

```python
for task in all_138_tasks:
    reset_container(task)
    run_gui_agent(task)  # GUI agent navigates UI and performs task

    # Evaluate with both verifiers on same post-agent state
    xml_result = original_xml_judge(task, dump_xml_tree())  # checks UI page
    adb_result = adb_verifier(task, container_url)           # checks device state

    record(task_id, xml_result["complete"], adb_result["complete"])
```

The key insight: XML verifier checks "did the agent end on the right page showing the result?" while ADB verifier checks "did the device state actually change?" For GUI agents these should agree. For terminal agents, only ADB makes sense.

### Step 2: Fix Disagreements

For each task where verifiers disagree:

1. Identify which verifier is correct (manually inspect the device state)
2. Fix the ADB verifier to match the original XML verifier's behavior
3. Document the fix and rationale
4. **Do NOT modify XML verifiers** — they define the benchmark ground truth

Known issues to address:
- `base.py:sqlite_query()` uses base64 encoding (bug fix, already applied)
- WAL checkpoint needed for Cantook/PiMusic databases
- Calendar verifier uses `strings` on Realm binary (weak, may need tightening)

### Step 3: Create Shared Evaluation Module

Create `eval_common.py` as the single evaluation entry point:

```python
# skyrl-agent/examples/run_androidlab/eval_common.py

from verifiers.verifier_map import get_verifier
from verifiers.query_detect_verifier import FUNCTION_MAP as QD_MAP

def evaluate_task(task_def, container_url, agent_answer=""):
    """Unified evaluation for ALL agents (GUI + Terminal).

    Args:
        task_def: Task definition dict with task_id, metric_type, etc.
        container_url: HTTP URL of the Android container.
        agent_answer: For query_detect tasks, the agent's text answer.

    Returns:
        dict: {"complete": bool, "1": bool, ...}
    """
    task_id = task_def["task_id"]
    metric_type = task_def["metric_type"]

    if metric_type == "operation":
        verifier_cls = get_verifier(task_id)
        if verifier_cls:
            return verifier_cls(container_url).is_successful()
        return {"complete": False, "no_verifier": True}

    elif metric_type == "query_detect":
        qd_cls = QD_MAP.get(task_id)
        if qd_cls:
            return qd_cls(container_url).is_successful(agent_answer=agent_answer)
        return {"complete": False, "no_verifier": True}

    return {"complete": False, "unknown_type": True}
```

### Step 4: Modify Agent Runners

**GUI agent (`run_gui_agent_androidlab.py`):**
```python
# Before (XML verifier):
xml_state = dump_xml_state(container_url)
result = original_judge.judge(xml_state, line)

# After (shared ADB verifier):
from eval_common import evaluate_task
result = evaluate_task(task_def, container_url, agent_answer=finish_description)
```

**Terminal agent (`run_claude_cli_androidlab.py`):**
```python
# Before (inline verification):
from verifiers.verifier_map import get_verifier
verifier = get_verifier(task_id)(container_url)
result = verifier.is_successful()

# After (shared):
from eval_common import evaluate_task
result = evaluate_task(task_def, container_url, agent_answer=finish_description)
```

**Oracle mode (`run_claude_cli_oracle.py`):**
```python
# Same change — use evaluate_task()
```

**Ground truth runner (`run_ground_truth.py`):**
```python
# Same change — use evaluate_task()
```

### Step 5: Reproduce Original Results

Run the GUI agent with unified ADB verifiers and compare:

```
Original paper (XML verifier):       26.8% SR on 138 tasks
Reproduction (ADB verifier):         should be ~26.8% ± 2%
```

If results diverge >2%, revisit Step 2 disagreements.

### Step 6: Run Full Comparison

```
                     AndroidWorld    AndroidLab
GUI Agent               X% SR          Y% SR
Terminal Agent           A% SR          B% SR
```

Both benchmarks now use agent-agnostic verifiers, enabling fair comparison.

---

## 5. File Changes Summary

| File | Change | Risk |
|------|--------|------|
| `eval_common.py` | **NEW** — shared evaluation function | Low |
| `run_gui_agent_androidlab.py` | Replace XML eval with `evaluate_task()` | Medium — must validate in Step 1 |
| `run_claude_cli_androidlab.py` | Replace inline verify with `evaluate_task()` | Low — same logic, just refactored |
| `run_claude_cli_oracle.py` | Replace `_evaluate_task()` with shared one | Low |
| `run_ground_truth.py` | Replace inline verify with `evaluate_task()` | Low |
| `verifiers/base.py` | Already fixed: base64 sqlite3 encoding | Already done |
| `cross_validate_dual.py` | Update or create v2 for Step 1 validation | Medium |

**Files NOT changed:**
- `Android-Lab/evaluation/tasks/` — original XML verifiers preserved as reference
- `androidlab_tasks.jsonl` — task data unchanged
- `androidlab_common.py` — broker/reset infra unchanged
- All verifier files in `verifiers/` — logic unchanged (only `base.py` already fixed)

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| ADB verifier disagrees with XML on edge cases | Step 1 cross-validation catches this before deployment |
| ADB verifier has bugs (false positives) | Ground truth commands (100 tasks) serve as regression test |
| Removing XML verifier loses historical comparability | Keep `Android-Lab/` as read-only reference; document the switch |
| SQLite queries fail due to WAL/timing | Already mitigated: base64 encoding + WAL checkpoint + force-stop |
| Calendar tasks (14) have weak Realm-based verification | Document as limitation; `strings` grep is best available without Java toolchain |

---

## 7. Definition of Done

- [ ] Cross-validation shows >95% agreement between XML and ADB verifiers
- [ ] All disagreements documented and ADB verifiers fixed
- [ ] `eval_common.py` created and used by all 4 runners
- [ ] GUI agent reproduction matches original paper within ±2% SR
- [ ] Full GUI vs Terminal comparison table produced for both benchmarks
- [ ] Design doc updated with actual cross-validation results
