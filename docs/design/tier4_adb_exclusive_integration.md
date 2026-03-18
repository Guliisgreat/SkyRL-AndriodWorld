# Tier 4: ADB-Exclusive Task Integration into AndroidWorld

**Status:** Draft
**Date:** 2026-03-18
**Branch:** `integrate_adb_exlusive`

---

## 1. Motivation

AndroidWorld's existing benchmark (91 action tasks + 25 IR tasks) is designed primarily for GUI agents that interact via screen taps and swipes. A growing class of **terminal/CLI agents** can solve tasks more efficiently through ADB shell commands — but the current benchmark doesn't measure this capability well because most tasks *can* be solved via the GUI.

**Tier 4** introduces tasks that are **ADB-exclusive**: they are impractical or impossible to solve reliably through the GUI alone. This creates a clean separation for evaluating terminal agent capabilities and extends AndroidWorld into a hybrid benchmark.

---

## 2. Constraint: Upstream `android_world` Is Read-Only

The `android_world` package is installed via pip and **must not be modified**. All custom code lives in `docker/android/skyrl_server/`. The integration strategy must:

1. Place Tier 4 task modules inside `skyrl_server/` (not in upstream `android_world/task_evals/`)
2. Import from `android_world` only as a dependency (base class, utilities)
3. Register tasks via `registry_ext.py` (the existing extension point)
4. Fix the current `tier4/__init__.py` which incorrectly imports from `android_world.task_evals.tier4` — a path that does not exist upstream

---

## 3. Current Tier 4 Pilot Tasks

Five task classes are implemented in `tier4/`, organized by domain:

### 3.1 Files (`tier4/files.py`)

| Task Class | Template | Complexity | Eval Type |
|---|---|---|---|
| `Tier4BulkDeleteTmpInDownloads` | "Delete all .tmp files in the Downloads folder." | 1.5 | **State-check**: Verifies no `.tmp` files remain via `find` |
| `Tier4CoverageNoTmpInDownloads` | "Confirm that there are no files with extension .tmp in the Downloads folder. If any exist, list their names." | 1.2 | **Output-check**: Compares `interaction_cache` against ground truth file list or "None" |

- **Why ADB-exclusive:** The Files app has no bulk-delete or wildcard filter. GUI agent must scroll, long-press, select each file individually — error-prone with variable file counts. ADB `find -delete` is a single command.

### 3.2 System (`tier4/system.py`)

| Task Class | Template | Complexity | Eval Type |
|---|---|---|---|
| `Tier4HiddenStateListAppVersions` | "List the version of each of the following apps: Markor, Pro Expense, Simple Calendar Pro." | 1.5 | **Output-check**: Verifies `interaction_cache` contains each app name + version string |

- **Why ADB-exclusive:** App versions are buried in Settings > Apps > [App] > scroll to bottom. GUI agent must navigate 3 separate app info screens. ADB `dumpsys package <pkg>` returns it in one command per app.

### 3.3 SMS (`tier4/sms.py`)

| Task Class | Template | Complexity | Eval Type |
|---|---|---|---|
| `Tier4AggregationCountUnreadSMS` | "How many unread SMS messages do you have in total?" | 1.2 | **Output-check**: Extracts integer from `interaction_cache`, matches ground truth count |
| `Tier4CrossAppSmsNumbersNotInContacts` | "List all phone numbers you have received SMS from in the last 7 days that are NOT in your contacts." | 2.0 | **Output-check**: Verifies all non-contact numbers appear in `interaction_cache` |

- **Why ADB-exclusive:** SMS app doesn't show unread count as a number. Cross-app comparison (SMS + Contacts) requires switching apps and manual cross-referencing — infeasible in a GUI agent loop. ADB `content query` provides direct database access.

---

## 4. Architecture & Integration Plan

### 4.1 How the Server Currently Works

```
docker/android/skyrl_server/
├── server.py          # FastAPI: /reset, /step, /step_adb endpoints
├── env.py             # AndroidWorldEnv (gymnasium wrapper)
├── registry_ext.py    # ExtendedTaskRegistry — intercepts family lookups
├── patches.py         # Runtime monkey-patches
└── logger_config.py
```

**Task flow:**
1. `env.py:_initialize_task_registry()` creates `ExtendedTaskRegistry()` and calls `get_registry(family=self.task_family)`
2. `get_registry()` returns `{class_name: TaskClass}` dict for the requested family
3. On `/reset`, `env.py:_select_and_initialize_task()` picks a task class, calls `generate_random_params()`, instantiates it, and calls `initialize_task(env)`
4. On `/step_adb` with `FINISH(...)`, `env.step()` calls `task.is_successful(env)` to compute reward

### 4.2 Target File Layout

Move Tier 4 task modules into `skyrl_server/` as a subpackage:

```
docker/android/skyrl_server/
├── server.py
├── env.py
├── registry_ext.py      # ← Add tier4 imports + TIER4 family
├── patches.py
├── logger_config.py
└── tier4/                # ← NEW: task modules live here
    ├── __init__.py       # ← Fix: use relative imports, not android_world.task_evals.tier4
    ├── files.py
    ├── system.py
    ├── sms.py
    └── tier4_test.py
```

### 4.3 Required Code Changes

#### A. Fix `tier4/__init__.py` imports

Current (broken — references non-existent upstream path):
```python
from android_world.task_evals.tier4 import files
from android_world.task_evals.tier4 import sms
from android_world.task_evals.tier4 import system
```

Fixed (relative imports within `skyrl_server.tier4`):
```python
from . import files
from . import sms
from . import system
```

#### B. Register in `registry_ext.py`

Add imports and a new family:

```python
# At top of file, add:
from .tier4 import files as tier4_files
from .tier4 import sms as tier4_sms
from .tier4 import system as tier4_system

_TIER4_TASKS = (
    tier4_files.Tier4BulkDeleteTmpInDownloads,
    tier4_files.Tier4CoverageNoTmpInDownloads,
    tier4_system.Tier4HiddenStateListAppVersions,
    tier4_sms.Tier4AggregationCountUnreadSMS,
    tier4_sms.Tier4CrossAppSmsNumbersNotInContacts,
)
```

In `ExtendedTaskRegistry`:

```python
TIER4 = 'tier4'
ADB_EXCLUSIVE = 'adb_exclusive'  # alias

def __init__(self):
    super().__init__()
    # ... existing tier registries ...
    self._tier4_reg = _build_registry(_TIER4_TASKS)

def get_registry(self, family):
    if family in (self.TIER4, self.ADB_EXCLUSIVE):
        return self._tier4_reg
    # ... existing logic ...
```

#### C. No changes to `env.py`

The env already calls `get_registry(self.task_family)`. To run Tier 4 tasks, pass `task_family="tier4"` when constructing the env (via env var or constructor arg). No code changes needed.

#### D. JSONL data file for inference

Create a data file for the inference pipeline. Task IDs start at 116 (after IR tasks 91–115):

```json
{"task_id": 116, "category": "tier4", "task": "Tier4BulkDeleteTmpInDownloads", "params": {}, "seed": 7}
{"task_id": 117, "category": "tier4", "task": "Tier4CoverageNoTmpInDownloads", "params": {"variant": "empty"}, "seed": 7}
{"task_id": 118, "category": "tier4", "task": "Tier4CoverageNoTmpInDownloads", "params": {"variant": "has_tmp"}, "seed": 7}
{"task_id": 119, "category": "tier4", "task": "Tier4HiddenStateListAppVersions", "params": {}, "seed": 7}
{"task_id": 120, "category": "tier4", "task": "Tier4AggregationCountUnreadSMS", "params": {}, "seed": 7}
{"task_id": 121, "category": "tier4", "task": "Tier4CrossAppSmsNumbersNotInContacts", "params": {}, "seed": 7}
```

### 4.4 Task Class Compliance

All five tasks correctly subclass `task_eval.TaskEval` (from pip `android_world`) and implement the required interface:

| Requirement | Status | Notes |
|---|---|---|
| `app_names` property | OK | Each task declares relevant app(s) |
| `complexity` property | OK | Range 1.2–2.0 |
| `schema` property | OK | JSON Schema for params |
| `template` string | OK | Natural language instruction |
| `initialize_task(env)` | OK | All call `super().initialize_task(env)` first |
| `is_successful(env) -> float` | OK | All call `super().is_successful(env)` first, return 0.0 or 1.0 |
| `tear_down(env)` | OK | All clean up created state and call `super().tear_down(env)` |
| `generate_random_params()` | OK | Returns `{}` or variant selection |

### 4.5 Dependencies (All from pip `android_world`)

| Dependency | Import Path | Purpose |
|---|---|---|
| `TaskEval` base class | `android_world.task_evals.task_eval` | Subclassing |
| `adb_utils` | `android_world.env.adb_utils` | `issue_generic_request`, `text_emulator`, `delete_contacts` |
| `device_constants` | `android_world.env.device_constants` | `DOWNLOAD_DATA` path |
| `file_utils` | `android_world.utils.file_utils` | `create_file` |
| `sms_validators` | `android_world.task_evals.common_validators.sms_validators` | `clear_sms_and_threads` |
| `contacts_utils` | `android_world.utils.contacts_utils` | `add_contact`, `list_contacts`, `clean_phone_number` |
| `user_data_generation` | `android_world.task_evals.utils.user_data_generation` | `generate_random_number` |

No new pip packages needed. All imports are from the existing `android_world` installation.

### 4.6 Evaluation Patterns

Tier 4 tasks use two distinct evaluation patterns:

1. **State-check** (`Tier4BulkDeleteTmpInDownloads`): Agent modifies device state; evaluator inspects device state via ADB. No `interaction_cache` needed.

2. **Output-check** (all others): Agent must report a text answer; evaluator reads `interaction_cache` and compares to ground truth. This relies on the agent issuing a `FINISH(content='...')` command in `/step_adb` mode, which the server translates to an `ANSWER` action setting `env.interaction_cache`.

### 4.7 Verification Script

`verify_tier4_on_emulator.py` is a standalone tool at the repo root that:
- Initializes each task on a real emulator
- Simulates correct agent behavior (runs the ADB commands an ideal agent would run)
- Simulates incorrect agent behavior (wrong output / no action)
- Checks `is_successful()` returns the expected score (12 scenarios: 6 correct + 6 incorrect)

**Note:** This script currently uses `from android_world.task_evals.tier4 import ...` which assumes the modules are in the upstream package. Once the modules move to `skyrl_server/tier4/`, this script's imports must be updated to point at the new location (or use `sys.path` manipulation to find `skyrl_server.tier4`).

---

## 5. Issues & Gaps in Current Implementation

### 5.1 Import Paths Are Wrong for the Target Layout

The `tier4/__init__.py` imports from `android_world.task_evals.tier4` — a path that doesn't exist in the pip package. Must be changed to relative imports (`.files`, `.sms`, `.system`) when placed inside `skyrl_server/`.

### 5.2 App Snapshot Restoration (Harmless but Noisy)

The upstream `TaskEval` base class has this flow:

```
initialize_task(env)
  → self._initialize_apps(env)
    → for app_name in self.app_names:
        app_snapshot.restore_snapshot(app_name, env.controller)
          → looks for /data/data/<pkg>/snapshot/ on emulator
          → if not found: raise RuntimeError("Snapshot not found in ...")
      → except RuntimeError:
          logging.warning("Skipping app snapshot loading: ...")
```

Tier 4 tasks declare `app_names` (e.g. `("files",)`, `("settings",)`) which triggers this restore attempt. But:
- Tier 4 tasks don't need app UI state — they operate on filesystem/content providers
- The snapshot directory may not exist (especially in a lean `tier4`-only image)
- The `RuntimeError` is caught and logged as a warning — execution continues normally

**Impact for `androidworld:tier4` image:** Since this image won't bundle app snapshots to stay lean, every task initialization will log this warning. This is functionally harmless but noisy. Options:
1. **Do nothing** — warnings are suppressed in production via log level config (current approach in `verify_tier4_on_emulator.py`)
2. **Set `app_names = ()`** — avoids the restore attempt entirely, but changes the TaskEval contract (some upstream code may inspect `app_names`)
3. **Override `_initialize_apps()`** — add a no-op override in each Tier 4 task class

Recommendation: Option 1 for now. If the image grows to include many tasks, consider Option 3 as a base class mixin.

### 5.3 SMS Timing Sensitivity

`Tier4AggregationCountUnreadSMS.initialize_task()` uses `time.sleep(1)` between SMS sends and `time.sleep(2)` after clearing. This is necessary for the SMS content provider to process insertions but adds ~7-9 seconds per task initialization. Acceptable for evaluation but worth noting for large-scale runs.

### 5.4 No Partial Credit

All tasks return 0.0 or 1.0 — no partial credit. For `Tier4CrossAppSmsNumbersNotInContacts`, if the agent finds 1 of 2 numbers, it gets 0.0. This is intentional (binary success) but could be revisited for training signal purposes (e.g., return `found/total`).

---

## 6. Future Task Expansion Plan

### 6.1 Task Categories for New ADB-Exclusive Tasks

Building on the five pilot patterns, here are categories for future expansion:

| Category | Pattern | Example Tasks |
|---|---|---|
| **Bulk Operations** | Agent modifies device state via ADB; eval checks state | Delete files by pattern, batch rename, clear app caches |
| **Coverage/Audit** | Agent inspects device state, reports findings | List large files, find duplicate files, check storage usage |
| **Hidden State** | Agent queries system info not visible in GUI | Battery stats, network config, running services, installed packages |
| **Aggregation** | Agent computes aggregate over structured data | Count by category, sum durations, find max/min |
| **Cross-App** | Agent correlates data across multiple content providers | Calendar events vs contacts, SMS vs call log, files vs downloads |
| **System Admin** | Agent performs system-level operations | Toggle developer options, manage permissions, configure proxy |

### 6.2 Recommended New Tasks (Priority Order)

**High priority** (low implementation effort, high differentiation):

1. **`Tier4ListLargeFilesInStorage`** — "List all files larger than 10MB on the device." Uses `find -size +10M`. GUI has no size filter.
2. **`Tier4CountAppsWithPermission`** — "How many apps have camera permission?" Uses `dumpsys package` + permission parsing. GUI requires checking each app individually.
3. **`Tier4BatteryDrainTopApps`** — "Which app consumed the most battery since last charge?" Uses `dumpsys batterystats`. Not exposed in simple format via GUI.
4. **`Tier4WifiSavedNetworks`** — "List all saved WiFi networks." Uses `cmd wifi list-networks`. GUI shows only nearby networks, not all saved.
5. **`Tier4CallLogSummary`** — "How many calls did you receive from unknown numbers this week?" Uses `content query --uri content://call_log/calls`. GUI requires scrolling through call history.

**Medium priority** (moderate effort):

6. **`Tier4DiskUsageByApp`** — "Which app uses the most storage?" Uses `dumpsys diskstats` or `du`.
7. **`Tier4FindDuplicateContacts`** — "List contacts that appear more than once." Requires content provider query + grouping.
8. **`Tier4ScheduledAlarms`** — "List all scheduled alarms." Uses `dumpsys alarm`.
9. **`Tier4RecentlyInstalledApps`** — "List apps installed in the last 7 days." Uses `dumpsys package` + install time parsing.
10. **`Tier4NetworkDataUsage`** — "How much mobile data has been used this month?" Uses `dumpsys netstats`.

### 6.3 Scaling the `skyrl_server/tier4/` Package

As task count grows, organize by domain within the `tier4/` subpackage:

```
docker/android/skyrl_server/tier4/
├── __init__.py           # Re-exports all task classes
├── files.py              # File system tasks
├── system.py             # System introspection tasks
├── sms.py                # SMS tasks
├── contacts.py           # Contact-related tasks (future)
├── call_log.py           # Call log tasks (future)
├── network.py            # Network/WiFi tasks (future)
└── tests/
    └── tier4_test.py     # Unit tests (mocked ADB)
```

If a domain grows beyond ~10 tasks, split into a subdirectory (e.g., `tier4/files/bulk.py`, `tier4/files/coverage.py`).

**Naming convention:** All classes prefixed with `Tier4` to distinguish from upstream GUI tasks (e.g., `Tier4BulkDeleteTmpInDownloads` vs upstream `FilesDeleteFile`).

**Adding a new task — checklist:**

1. Create task class in the appropriate domain module (e.g., `tier4/contacts.py`)
2. Subclass `task_eval.TaskEval`, implement all abstract properties/methods
3. Add class to `_TIER4_TASKS` tuple in `registry_ext.py`
4. Re-export from `tier4/__init__.py`
5. Add unit test in `tier4/tests/tier4_test.py` (mock ADB responses)
6. Add correct + wrong scenario to `verify_tier4_on_emulator.py`
7. Add JSONL entry for inference data file

### 6.4 Parameter Schemas for Richer Randomization

As tasks grow more complex, use richer schemas with constrained randomization:

```python
schema = {
    "type": "object",
    "properties": {
        "file_extension": {"type": "string", "enum": [".tmp", ".log", ".bak"]},
        "min_count": {"type": "integer", "minimum": 2, "maximum": 10},
    },
    "required": ["file_extension"],
}
```

### 6.5 Partial Credit for RL Training

For training (RL reward signal), consider a `reward_mode` toggle:
- `binary`: 0.0 or 1.0 (current behavior, for evaluation)
- `proportional`: `correct_items / total_items` (for training signal)

This can be implemented as a class-level attribute or constructor parameter without changing the `TaskEval` interface.

### 6.6 Testing Strategy

Each new task module should include:

1. **Unit tests** (like `tier4_test.py`) — Mock ADB responses, test `is_successful()` for correct/incorrect outputs
2. **Emulator verification** — Add entry to `verify_tier4_on_emulator.py` with correct + wrong simulation
3. **Agent smoke test** — Run actual T3A-ADB agent on 1 instance to confirm end-to-end flow

---

## 7. Docker Image: `androidworld:tier4`

### 7.1 Image Hierarchy

The existing image chain is:

```
ubuntu:22.04
  └── androidworld:v8       (Python 3.11, Android SDK, emulator, AVD)
        └── androidworld:2026  (uninstalls forked pkgs, installs upstream pip, adds skyrl_server/)
```

The new tier4 image layers on top of `:2026`:

```
androidworld:2026
  └── androidworld:tier4     (adds skyrl_server/tier4/, sets TASK_FAMILY=tier4)
```

### 7.2 Dockerfile.tier4

```dockerfile
# AndroidWorld Tier 4 — ADB-exclusive tasks only.
#
# Layers on top of androidworld:2026 (upstream pip packages + skyrl_server).
# Adds tier4 task modules and configures the server to serve only tier4 tasks.
#
# Build:
#   cd docker/android
#   docker build -f Dockerfile.tier4 -t androidworld:tier4 .
#
# Requires: androidworld:2026

FROM androidworld:2026

WORKDIR /data

# Copy tier4 task modules into skyrl_server package
COPY skyrl_server/tier4/ /data/skyrl_server/tier4/

# Default to tier4 task family (can be overridden via env var)
ENV TASK_FAMILY=tier4

ENTRYPOINT ["bash", "/data/entrypoint.sh"]
```

### 7.3 Why a Separate Image?

| Concern | `:2026` (full) | `:tier4` (proposed) |
|---|---|---|
| Task set | 91 action + 25 IR | 5 tier4 (growing) |
| App snapshots | Required for GUI tasks | Not needed — tasks use ADB/content providers |
| Screenshot capture | Required for GUI agents | Can skip (`ENV_SKIP_SCREENSHOT=true`) |
| Agent type | GUI (M3A/T3A) or ADB | ADB-only (T3A-ADB) |
| Image size delta | Baseline | +tier4/ modules only (~20KB) |

The images share the same base, so `:tier4` is just a thin layer adding the task modules. The key difference is the `TASK_FAMILY=tier4` default — the server will only serve Tier 4 tasks from the registry.

### 7.4 Registry Wiring for `TASK_FAMILY=tier4`

`env.py` reads `task_family` from the constructor (which can be set via env var or server config). The flow:

```
env.py: AndroidWorldEnv(task_family="tier4")
  → _initialize_task_registry()
    → ExtendedTaskRegistry().get_registry("tier4")
      → returns {
          "Tier4BulkDeleteTmpInDownloads": <class>,
          "Tier4CoverageNoTmpInDownloads": <class>,
          "Tier4HiddenStateListAppVersions": <class>,
          "Tier4AggregationCountUnreadSMS": <class>,
          "Tier4CrossAppSmsNumbersNotInContacts": <class>,
        }
  → self.all_tasks = [(name, cls), ...]  # 5 tasks
```

`env.py` needs a small change to read `TASK_FAMILY` from environment:

```python
# In AndroidWorldEnv.__init__():
task_family = os.environ.get("TASK_FAMILY", task_family)
```

This lets the Docker image control the task family via `ENV TASK_FAMILY=tier4` without code changes at the call site.

### 7.5 What the Image Does NOT Need

Since Tier 4 tasks operate via ADB commands and content providers (not GUI interaction):

- **No app snapshots** — tasks don't restore app state, they create/query state directly
- **No screenshot capture** — set `ENV_SKIP_SCREENSHOT=true` for faster step cycles
- **No a11y tree extraction** — ADB agents don't use UI elements

These can be configured via env vars when running the container:

```bash
docker run -d \
  -e TASK_FAMILY=tier4 \
  -e ENV_SKIP_SCREENSHOT=true \
  androidworld:tier4
```

### 7.6 Build & Run

```bash
# Build (requires androidworld:2026 as base)
cd docker/android
docker build -f Dockerfile.tier4 -t androidworld:tier4 .

# Run single container
docker run -d --name tier4-test \
  -e TASK_FAMILY=tier4 \
  -e ENV_SKIP_SCREENSHOT=true \
  -e SERVER_PORT=5000 \
  androidworld:tier4

# With pool broker (16+ containers)
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 \
  --docker-image androidworld:tier4 \
  --port 9200
```

---

## 8. Integration Checklist

```
[ ] Move tier4/ into docker/android/skyrl_server/tier4/
[ ] Fix tier4/__init__.py to use relative imports (from . import files, sms, system)
[ ] Add tier4 imports and TIER4 family to registry_ext.py
[ ] Add TASK_FAMILY env var reading to env.py
[ ] Update verify_tier4_on_emulator.py imports to point at skyrl_server.tier4
[ ] Generate tier4 JSONL data file (seed 7, 6 instances for 5 tasks)
[ ] Create Dockerfile.tier4
[ ] Build androidworld:tier4 image (requires androidworld:2026 base)
[ ] Run verify_tier4_on_emulator.py on tier4 container
[ ] Run unit tests: python -m pytest skyrl_server/tier4/tier4_test.py
[ ] Run T3A-ADB agent on tier4 tasks (smoke test with task_family="tier4")
```

---

## 9. Summary

The Tier 4 pilot is well-designed and integration-ready:

- **5 task classes** across 3 domains (files, system, SMS) following established `TaskEval` patterns
- **2 evaluation patterns** (state-check, output-check) that compose well with existing infrastructure
- **No upstream changes needed** — tasks subclass pip `TaskEval`, register via `registry_ext.py`
- **Comprehensive verification** — 12-scenario test script with positive/negative cases
- **Separate Docker image** — `androidworld:tier4` layers on `:2026`, adds only tier4 modules + `TASK_FAMILY=tier4` default
- **Clear expansion path** — category taxonomy and naming convention support 50+ future tasks

The main integration work is:
1. Moving `tier4/` into `skyrl_server/tier4/` and fixing imports to be relative
2. Adding the `TIER4` family to `registry_ext.py`
3. Creating `Dockerfile.tier4` and building the image
4. Generating JSONL data for the inference pipeline
