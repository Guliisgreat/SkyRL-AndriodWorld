# Design Doc: Android-Lab Benchmark Integration

**Date:** 2026-03-21
**Status:** Draft
**Goal:** Evaluate our terminal agents (mini-swe-agent, Claude Code CLI, Terminus-2) on the Android-Lab benchmark and demonstrate that terminal agents can outperform GUI agents.

---

## 1. Android-Lab Architecture Overview

### 1.1 What is Android-Lab?

[Android-Lab](https://github.com/THUDM/Android-Lab) is a benchmark and training framework for Android agents. It has **138 tasks** across **9 apps** (Bluecoins, Calendar, Cantook, Clock, Contacts, Maps.me, PiMusic, Settings, Zoom). Unlike AndroidWorld (which generates parametric task variants), Android-Lab uses fixed, hand-authored tasks with per-task evaluation judges.

### 1.2 Task Format

Tasks are defined in per-app YAML files under `evaluation/config/`:

```yaml
APP: bluecoins
package: com.rammigsoftware.bluecoins
tasks:
  - task_id: bluecoins_1
    task: "Could you tell me how much I spent on May 10, 2024?"
    metric_type: query_detect      # or "operation"
    metric_func: evaluation.tasks.bluecoins
    adb_query: "adb shell ..."     # optional per-step state query
```

Key fields:
- **`task_id`** — `{app}_{number}` string (e.g., `calendar_14`)
- **`task`** — Natural language instruction
- **`metric_type`** — `operation` (check UI state) or `query_detect` (LLM judge on agent's answer)
- **`metric_func`** — Python module containing per-task judge classes
- **`adb_query`** — Optional ADB command for per-step state inspection

### 1.3 Task Categories

There is **no explicit train/test split**. Tasks are categorized by:
- **App** — 9 apps, each with separate YAML
- **metric_type** — `operation` (UI manipulation) vs `query_detect` (information retrieval)
- **Informal sub-types** — `query`, `operation_create`, `operation_edit` (visible in YAML comments)

### 1.4 Evaluation System

Evaluation is **two-phase**:

**Phase 1 (online):** Per-step auto-stop — if the agent repeats the same action 5+ times, execution halts.

**Phase 2 (post-hoc via `generate_result.py`):** Each task has a judge class inheriting `SingleTask`:

```python
class SingleTask_bluecoins_6(SingleTask):
    def judge(self, xml_compressed_tree, line):
        bill = extract_bills_NewEditBK(xml_compressed_tree)
        return {
            "judge_page": True,
            "1": bill.get("type") == "Expense",
            "2": bill.get("cash") in ("512", "512.00"),
            "complete": bill.get("type") == "Expense" and bill.get("cash") in ("512", "512.00"),
        }
```

Two evaluation strategies:
1. **`operation`** — Parses compressed XML tree at each step to check if sub-goals are met (correct page, correct values)
2. **`query_detect`** — Uses LLM judge (GPT-4o) to compare agent's final answer against ground truth

**Metrics:**
- **Success Rate (SR)** — `complete == True` / total tasks
- **Sub-Goal SR** — Partial accuracy across sub-goals
- **Reversed Redundancy Ratio (RRR)** — `ground_truth_steps / actual_steps` (efficiency)
- **Reasonable Operation Ratio (ROR)** — `1 - redundant_screenshots / total_steps`

### 1.5 Environment Management

**Docker mode** (relevant for our integration):
- Creates fresh Docker container per task: `docker run -itd --privileged -p {port}:{docker_port} {image}`
- Starts AVD inside container via HTTP API (`/start` endpoint)
- After each task: `docker stop` + `docker rm` (complete isolation)
- Pre-task setup: `adb root`, set GPS, fix date to `2024-05-10 12:00:00`, launch target app

**Key difference from AndroidWorld:** Android-Lab assumes date is **2024-05-10 12:00:00** and pre-installs specific app states in the AVD snapshot. There is no parametric seed-based task reset like AndroidWorld's `/reset` endpoint.

### 1.6 Agent Interface

Agents implement a simple protocol:

```python
class Agent:
    def act(self, messages: List[Dict]) -> str:          # Returns Python code snippet
    def prompt_to_message(self, prompt, images) -> dict  # Format for multimodal
    def system_prompt(self, instruction) -> str           # Task-aware system prompt
```

The agent's response is a Python code block that is `exec()`'d with available action functions:

```python
# High-level API
do(action="Tap", element=[x1, y1, x2, y2])
do(action="Type", text="hello")
do(action="Swipe", element=[x1,y1,x2,y2], direction="up", dist="medium")
do(action="Long Press", element=[x1,y1,x2,y2])
do(action="Home"); do(action="Back"); do(action="Enter"); do(action="Wait")
do(action="Launch", app="Clock")
finish(message="The answer is 42")
```

**Observation modes:**
- **XML-only** — Compressed XML tree as text, elements referenced by `[x1, y1, x2, y2]`
- **Screenshot (SoM)** — Labeled screenshot + XML, elements referenced by numeric index

### 1.7 Agent Lifecycle (Full Flow)

1. Parse config YAML → instantiate agent
2. Load all task YAMLs from `evaluation/config/`
3. For each task:
   a. Create Docker container (or clone AVD)
   b. Boot emulator, set date/GPS, launch target app
   c. **Step loop** (max 25 rounds):
      - Take screenshot + dump XML via `uiautomator dump`
      - Compress XML → send to agent
      - Agent returns code → execute via `page_executor`
      - Save trace (screenshot, XML, action, response)
      - If `finish` action → break
   d. Destroy container
4. Post-hoc evaluation via `generate_result.py` → Excel report

---

## 2. Key Differences: Android-Lab vs AndroidWorld

| Aspect | AndroidWorld | Android-Lab |
|--------|-------------|-------------|
| Task count | 87 terminal-only (val) / 234 unseen | 138 (fixed) |
| Task format | JSONL with seed, difficulty | YAML with metric_type, judge class |
| Task reset | `/reset` API with task_id + seed | Fresh Docker container + AVD snapshot |
| Evaluation | Server-side via `/step` action | Post-hoc XML parsing + LLM judge |
| Environment date | Current date | Fixed: 2024-05-10 12:00:00 |
| Apps | Android system + 3rd party apps | 9 specific apps |
| Parametric | Yes (seed-based variations) | No (fixed instances) |
| Agent protocol | HTTP step API | Python `exec()` of agent code |
| Our infra | Container pool + broker | Must adapt |

---

## 3. Integration Plan: Terminal Agents on Android-Lab

### 3.1 Core Challenge

Android-Lab assumes a **GUI agent** that:
1. Receives XML tree or screenshot at each step
2. Returns Python code targeting specific UI elements by coordinates
3. Is evaluated by checking XML/UI state after the agent finishes

Our terminal agents operate differently:
1. Receive ADB/terminal access to the device
2. Execute shell commands (ADB, SQL queries, file operations)
3. Report task completion via `finish` action

The key integration challenge is bridging these two paradigms while using Android-Lab's evaluation system.

### 3.2 Architecture: Two-Layer Approach

```
┌─────────────────────────────────────────────────────┐
│             Android-Lab Evaluator (hybrid)           │
│  • query_detect → LLM judge (as-is)                 │
│  • operation → post-agent XML dump → judge classes   │
└──────────────────────┬──────────────────────────────┘
                       │ reads traces / live XML
┌──────────────────────┴──────────────────────────────┐
│     SkyRL Runner + AndroidLabPoolBroker              │
│  (extends ContainerPoolBroker)                       │
│  • Reset = snapshot restore + date/GPS/app launch    │
│  • Acquires container, runs agent, returns container │
│  • Post-agent: launch app → XML dump → evaluate     │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP: ADB, snapshot restore
┌──────────────────────┴──────────────────────────────┐
│       Android-Lab Docker Image (official)            │
│  • 9 apps pre-installed with pre-loaded data         │
│  • Used as-is — NOT built from androidworld:v9       │
└─────────────────────────────────────────────────────┘
```

### 3.3 Step-by-Step Integration Plan

#### Step 1: Prepare Android-Lab Docker Image

**Approach:** Use Android-Lab's official Docker image directly — do NOT build from our `androidworld:v9`.

Android-Lab provides its own Docker image with all 9 apps pre-installed and pre-loaded data baked into the AVD snapshot. Attempting to recreate this from scratch is error-prone and unnecessary.

1. Pull the official Android-Lab Docker image (check the repo's README / releases for the image name, likely on Docker Hub or a download link)
2. Verify the image boots correctly and all 9 apps launch with expected pre-loaded state
3. Tag locally as `androidlab:v1` for our infrastructure
4. Test that snapshot save/restore works within the container (our broker needs this)
5. If the image lacks an HTTP API compatible with our broker, add a thin wrapper (see Step 3)

**Key considerations:**
- The Android-Lab image likely has a different internal API than our `skyrl_server`. We need to understand its endpoints (`/start`, ADB access pattern) and adapt our broker accordingly.
- The image may use a different Android version than our `androidworld:v9` — that's fine, we use it as-is.
- Do NOT modify the image's app data or AVD snapshot — this ensures evaluation results are comparable to published baselines.

#### Step 2: Convert Android-Lab Tasks to JSONL

Convert the 138 tasks from YAML to our JSONL format:

```python
# converter script
import yaml, json, os

tasks = []
for yaml_file in os.listdir("evaluation/config/"):
    with open(f"evaluation/config/{yaml_file}") as f:
        data = yaml.safe_load(f)
    app = data["APP"]
    package = data["package"]
    for t in data["tasks"]:
        tasks.append({
            "task_id": t["task_id"],           # string: "bluecoins_1"
            "task": t["task"],                  # instruction text
            "app": app,
            "package": package,
            "metric_type": t["metric_type"],   # "operation" or "query_detect"
            "metric_func": t.get("metric_func", ""),
            "adb_query": t.get("adb_query", ""),
            "seed": 0,                         # fixed (no parametric variation)
        })

with open("androidlab_tasks.jsonl", "w") as f:
    for t in tasks:
        f.write(json.dumps(t) + "\n")
```

**Note:** `task_id` is a string in Android-Lab (e.g., `"bluecoins_1"`), unlike AndroidWorld's integer IDs. Our infrastructure must handle this.

#### Step 3: Adapt Broker for Android-Lab

Android-Lab requires a different reset than AndroidWorld:

```
AndroidWorld reset: POST /reset {task_id, seed} → parameterized task setup
Android-Lab reset: Restore AVD snapshot → fixed pre-loaded state + date/GPS/app setup
```

**Proposed approach:** Create a new broker class `AndroidLabPoolBroker` that extends `ContainerPoolBroker`.

The new broker class lives alongside the existing one and handles Android-Lab-specific concerns:

```python
class AndroidLabPoolBroker(ContainerPoolBroker):
    """Broker compatible with Android-Lab Docker images.

    Key differences from ContainerPoolBroker:
    - Uses Android-Lab's Docker image (not androidworld:v9)
    - Reset = AVD snapshot restore + fixed date/GPS + app launch
    - No parameterized task setup (no seed-based reset)
    - Understands Android-Lab's container API (if different)
    """

    async def reset_container(self, env_id: int, task_def: dict):
        """Reset via snapshot restore, then apply Android-Lab pre-task setup."""
        # 1. Restore AVD snapshot (reuse existing snapshot restore mechanism)
        await self._restore_snapshot(env_id)
        # 2. Set fixed date
        await self._adb(env_id, "shell date '2024-05-10 12:00:00'")
        # 3. Set GPS
        await self._adb(env_id, "shell settings put secure location_providers_allowed gps")
        await self._adb(env_id, "shell am broadcast -a android.intent.action.SET_GPS "
                                "-e lat 37.438 -e lon -122.156")
        # 4. Launch target app (from task_def)
        package = task_def.get("package", "")
        if package:
            await self._adb(env_id, f"shell monkey -p {package} "
                                    "-c android.intent.category.LAUNCHER 1")
```

**Why a new class instead of a mode flag:**
- Clean separation — Android-Lab's image, API, and reset semantics are fundamentally different
- The existing `ContainerPoolBroker` stays untouched (no risk to AndroidWorld runs)
- Can be launched with the same CLI: `python pool_broker.py --class androidlab --image androidlab:v1`
- Snapshot restore as the preferred reset mechanism (fast, reliable, stateless)

#### Step 4: Adapt Evaluation — Hybrid Strategy

This is the most critical piece. We use a **hybrid evaluation strategy** that combines Android-Lab's native evaluators with post-agent UI state capture.

**Strategy: Reproduce first, then extend.**

**Phase A — Reproduce original paper results (prerequisite):**
Before running any terminal agent, first reproduce Android-Lab's published GUI baselines using their own evaluation pipeline on our infrastructure. This validates:
1. The Docker image has correct app state
2. Our broker reset produces the same starting conditions
3. The evaluation judges produce consistent results
4. Our XML compression matches theirs

Run Android-Lab's native GUI agent (GPT-4o XML-only mode) through our `AndroidLabPoolBroker` and compare SR against published numbers. If results differ by >5%, debug before proceeding.

**Phase B — Hybrid evaluation for terminal agents:**

The hybrid approach handles both metric types:

**`query_detect` tasks (40%):** Use Android-Lab's LLM judge as-is. The terminal agent provides an answer via `finish --description`, and the LLM judge compares it to the ground truth. Zero adaptation needed — this works identically for terminal and GUI agents.

**`operation` tasks (60%):** Use a two-step process:
1. **Terminal agent executes** — modifies app state via ADB/SQL/shell commands
2. **Post-agent UI capture** — automatically launch the target app, wait for UI to settle, then dump XML via `uiautomator dump`. Feed the compressed XML to Android-Lab's original judge class.

This works because most backend state changes (database inserts, settings modifications, file changes) are reflected in the UI when the app is opened. The judge checks UI state, and if the terminal agent correctly modified the underlying data, the UI will show the right values.

```python
def evaluate_hybrid(task_def, container_url, agent_answer=None):
    """Hybrid evaluation: LLM judge for query_detect, XML judge for operation."""
    task_id = task_def["task_id"]
    metric_type = task_def["metric_type"]

    if metric_type == "query_detect":
        # Direct LLM judge — identical for terminal and GUI agents
        return llm_judge(task_def, agent_answer)

    elif metric_type == "operation":
        # Post-agent: launch app → wait → dump XML → run judge
        package = task_def["package"]
        adb_exec(container_url, f"adb shell monkey -p {package} "
                                "-c android.intent.category.LAUNCHER 1")
        time.sleep(8)  # wait for app to fully render

        # Some judges check specific pages — may need app-specific navigation
        # Start with just launching the app; add navigation if needed per-app
        xml = adb_exec(container_url,
            "adb shell uiautomator dump /sdcard/window_dump.xml "
            "&& adb shell cat /sdcard/window_dump.xml")
        compressed = compress_xml(xml)

        judge_cls = load_judge(task_def["metric_func"], task_id)
        result = judge_cls().judge(compressed, "")
        return result.get("complete", False)
```

**Known limitation:** Some `operation` judges call `check_page()` which verifies the agent is on a specific screen (e.g., the "edit expense" form). Terminal agents won't be on that page. For these tasks, we may need per-app navigation scripts to open the correct page after the agent finishes. Track which tasks fail due to `judge_page=False` vs `complete=False` to isolate this.

#### Step 5: Build Android-Lab Runner Scripts

Create runner scripts following our existing pattern:

```
skyrl-agent/examples/run_androidlab/
├── androidlab_common.py          # Shared helpers (task loading, eval, reset)
├── run_claude_cli_androidlab.py  # Claude Code CLI on Android-Lab
├── run_terminus2_androidlab.py   # Terminus-2 on Android-Lab
├── run_mini_swe_androidlab.py    # Mini-SWE on Android-Lab
└── evaluate_results.py           # Post-hoc evaluation using Android-Lab judges
```

**`androidlab_common.py`** will contain:
- Task JSONL loader with Android-Lab schema
- Container reset with Android-Lab mode (date, GPS, app launch)
- Post-task XML dump and evaluation bridge
- Integration with `run_parallel` / `run_sequential` from `claude_cli_common.py`

Each agent runner will:
1. Load Android-Lab tasks from JSONL
2. For each task: reset container → run agent → dump final XML → evaluate
3. Save results in our standard format

#### Step 6: Post-hoc Evaluation Bridge

The key bridge between our agent output and Android-Lab's evaluator:

```python
def evaluate_androidlab_task(task_def, container_url, agent_answer=None):
    """Run Android-Lab evaluation after agent finishes."""
    task_id = task_def["task_id"]
    metric_type = task_def["metric_type"]

    if metric_type == "query_detect":
        # LLM judge: compare agent's answer to ground truth
        return llm_judge(task_def, agent_answer)

    elif metric_type == "operation":
        # Launch app and dump XML
        package = task_def["package"]
        adb_exec(container_url, f"adb shell monkey -p {package} -c android.intent.category.LAUNCHER 1")
        time.sleep(5)
        xml = adb_exec(container_url, "adb shell uiautomator dump /sdcard/window_dump.xml && adb shell cat /sdcard/window_dump.xml")
        compressed = compress_xml(xml)

        # Load Android-Lab judge class
        judge_cls = load_judge(task_def["metric_func"], task_id)
        result = judge_cls().judge(compressed, "")
        return result.get("complete", False)
```

### 3.4 Agent-Specific Considerations

#### Claude Code CLI
- Already works via `android_env.py` — same ADB/shell interface
- System prompt needs adjustment for Android-Lab date assumption (2024-05-10)
- `query_detect` tasks: agent must output the answer explicitly via `finish --description`
- Strongest baseline, expected highest SR

#### Terminus-2
- Works via `SkyrlServerEnvironment` — same container HTTP API
- Template must mention fixed date and app context
- Multi-command batching should work well for setup + query patterns
- Good for structured tasks (create event, set alarm)

#### Mini-SWE Agent
- Works via `AndroidWorldEnvironment` — subprocess to `android_env.py`
- Simplest action space (single bash command per step)
- Best for RL training loop integration
- Lower expected SR but best for demonstrating RL improvement

### 3.5 Apps and Terminal Agent Advantages

Analysis of 9 Android-Lab apps and terminal agent potential:

| App | Tasks | Terminal Advantage | Notes |
|-----|-------|-------------------|-------|
| **Bluecoins** | 15 | HIGH | SQLite database — can query/insert directly |
| **Calendar** | 14 | HIGH | `content://` provider — insert/query events via ADB |
| **Contacts** | ? | HIGH | `content://` provider — full CRUD via ADB |
| **Clock** | ? | MEDIUM | Alarms via `content://` provider, some UI-only features |
| **Settings** | ? | HIGH | Direct `settings put` commands — fastest possible |
| **Cantook** | ? | LOW | E-reader — likely requires UI navigation |
| **Maps.me** | ? | LOW | Map interactions likely UI-dependent |
| **PiMusic** | ? | MEDIUM | File operations + media scanner, some UI-only |
| **Zoom** | ? | LOW | Video conferencing — highly UI-dependent |

**Expected strong categories for terminal agents:**
- Settings manipulation (direct `settings put/get`)
- Calendar CRUD (content provider)
- Contacts CRUD (content provider)
- Bluecoins queries (SQLite)
- Information retrieval tasks (`query_detect`) across all apps

---

## 4. Proving Terminal > GUI: Experiment Design

### 4.1 Hypothesis

Terminal agents outperform GUI agents on Android-Lab because:
1. **Speed** — ADB commands execute instantly vs multi-step UI navigation
2. **Reliability** — No coordinate targeting errors, no UI state confusion
3. **Direct data access** — SQLite/content providers bypass UI entirely
4. **Composability** — Shell pipelines can combine multiple operations atomically

### 4.2 Baseline Comparison

**GUI baselines (from Android-Lab paper):**
- GPT-4o (XML-only): ~25% SR
- GPT-4o (SoM/screenshot): ~30% SR
- Fine-tuned models (CogAgent, etc.): 15-25% SR

**Our terminal agent targets:**
- Claude Code CLI (claude-opus-4-6): **target 50%+ SR**
- Terminus-2 (claude-sonnet-4-6): **target 35%+ SR**
- Mini-SWE Agent (open-source model): **target 25%+ SR**

### 4.3 Controlled Experiment Plan

**Phase 1: Infrastructure + Reproduction (1 week)**
- Pull Android-Lab Docker image, set up `AndroidLabPoolBroker`
- Convert tasks to JSONL, build evaluation pipeline
- **Reproduce original paper results**: run GPT-4o XML-only GUI agent through our infra
- Validate SR matches published baseline (within 5%). This is the gate for Phase 2.

**Phase 2: Terminal Agent Benchmark (1 week)**
- Run all 138 tasks with Claude Code CLI
- Run all 138 tasks with Terminus-2
- Run all 138 tasks with Mini-SWE Agent
- Each agent gets 3 runs for variance estimation

**Phase 3: Analysis (3 days)**
- Per-app breakdown: where do terminal agents win/lose?
- Per-metric-type breakdown: `operation` vs `query_detect`
- Efficiency comparison: steps, tokens, cost, time
- Failure mode analysis: categorize `judge_page` failures vs `complete` failures

### 4.4 Fair Comparison Considerations

1. **Same model, different interface:** Run GPT-4o as both GUI agent (Android-Lab's native mode) and terminal agent (our Terminus-2) to isolate the interface effect
2. **Step budget:** Android-Lab default is 25 steps; our agents use 30. Normalize to 25 for fair comparison.
3. **Date handling:** Ensure our terminal agents know the date is 2024-05-10
4. **App pre-state:** Verify the Docker image has identical pre-loaded data to Android-Lab's AVD snapshot

### 4.5 Expected Results Narrative

**Strong result:** Terminal agents match or exceed GUI on `query_detect` tasks (information retrieval is natural for terminal) AND outperform on a subset of `operation` tasks (database/settings manipulation).

**Headline metric:** Claude Code CLI achieves 50%+ SR on Android-Lab, surpassing GPT-4o's 30% (best GUI baseline). This would be a **67%+ relative improvement**.

**Potential weaknesses:**
- **Cantook/Maps.me/Zoom:** These apps may have limited terminal affordances; expect lower SR
- **UI-specific operations:** Some tasks require visual feedback (e.g., "make the map show satellite view") that terminal agents cannot replicate
- **Evaluator bias:** `operation` evaluators check XML/UI state — if terminal agent modifies backend state without UI reflection, evaluation may incorrectly fail

---

## 5. Implementation Roadmap

### Phase 0: Docker Image + Broker
- [ ] Pull/download Android-Lab's official Docker image
- [ ] Verify all 9 apps launch correctly with expected pre-loaded data
- [ ] Test snapshot save/restore within the container
- [ ] Implement `AndroidLabPoolBroker` extending `ContainerPoolBroker`
- [ ] Reset logic: snapshot restore → set date (2024-05-10) → set GPS → launch app
- [ ] Verify broker can manage a pool of Android-Lab containers

### Phase 1: Task + Evaluation Pipeline
- [ ] Write task YAML → JSONL converter
- [ ] Port Android-Lab's XML compression (`UIXMLTree`) for evaluation compatibility
- [ ] Implement hybrid evaluator (LLM judge for `query_detect`, XML judge for `operation`)
- [ ] Implement `androidlab_common.py` with reset, eval, and runner helpers
- [ ] End-to-end test: 1 task manually to validate pipeline

### Phase 2: Reproduce Original Paper Results (PREREQUISITE)
- [ ] Run Android-Lab's native GUI agent (GPT-4o XML-only) via `AndroidLabPoolBroker`
- [ ] Compare SR against published baselines (should be within 5%)
- [ ] Debug any discrepancies (image state, eval judges, XML compression)
- [ ] Document reproduced results as our ground-truth baseline

### Phase 3: Terminal Agent Runners
- [ ] `run_claude_cli_androidlab.py` — Claude Code CLI runner
- [ ] `run_terminus2_androidlab.py` — Terminus-2 runner
- [ ] `run_mini_swe_androidlab.py` — Mini-SWE runner
- [ ] System prompt variants mentioning Android-Lab context (fixed date, apps)
- [ ] Post-agent app launch + XML dump for `operation` task evaluation

### Phase 4: Full Benchmark Runs
- [ ] 3x runs of each terminal agent on all 138 tasks
- [ ] Results collection and analysis
- [ ] Per-app, per-type breakdown
- [ ] Comparison against reproduced GUI baselines (Phase 2)

### Phase 5: Write-up
- [ ] Results doc with tables, charts
- [ ] Failure mode categorization (judge_page failures vs complete failures)
- [ ] Terminal vs GUI advantage analysis per app category

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Android-Lab Docker image unavailable or broken | Low | High | Check repo releases/issues; contact authors if needed |
| Reproduced GUI baseline differs from paper | Medium | High | Gate on reproduction before terminal runs; debug image/eval |
| Evaluator rejects terminal agent state (`judge_page=False`) | High | High | Post-agent app launch + XML dump; per-app navigation scripts if needed |
| Some apps have no terminal affordance | High | Medium | Accept lower SR on UI-only apps; focus analysis on terminal-friendly apps |
| Android-Lab image incompatible with broker snapshot restore | Medium | Medium | Test early; fall back to fresh container per task if needed |
| Cost of 3x 138 tasks with Claude Opus | Low | Medium | ~$200-400 total; acceptable for benchmark |

---

## 7. Open Questions

1. **AVD snapshot access:** Does Android-Lab provide downloadable snapshots, or must we recreate from scratch?
2. **Android version:** What Android version does Android-Lab target? Our `androidworld:v9` is Android 14 — is this compatible?
3. **App versions:** Are specific APK versions required, or do latest versions work?
4. **Evaluator portability:** Can we run Android-Lab's evaluation code standalone (outside their Docker setup)?
5. **Zoom tasks:** Do Zoom tasks require actual account login? If so, they may need to be excluded.
6. **Maps.me tasks:** Do Maps.me tasks require internet for map data, or is it pre-cached?
