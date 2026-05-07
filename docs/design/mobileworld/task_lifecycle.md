# MobileWorld Task Lifecycle: Complete Data Flow

**Date**: 2026-03-30

## Overview

Each MobileWorld task follows this lifecycle:

```
Server Startup → Device Init → Task Init → Agent Loop → Eval → Teardown
```

All tasks are Python classes in `MobileWorld/src/mobile_world/tasks/definitions/{category}/`. There are no JSON task files — the server discovers them at startup.

## 1. Server Startup

```
entrypoint.sh
  ├── start-docker.sh (Docker-in-Docker for Mastodon/Mattermost)
  ├── docker load (pre-built backend images)
  ├── start_emulator.sh (Android emulator)
  ├── socat (ADB port relay: 5556 → emulator ADB)
  └── mobile-world server --port 6800
        └── initialize_suite_family("mobile_world")
              └── TaskRegistry()
                    └── _scan_and_register_tasks()
                          └── for each .py in tasks/definitions/**/:
                                importlib.util.spec_from_file_location()
                                spec.loader.exec_module(module)
                                for cls in module if issubclass(cls, BaseTask):
                                  tasks[cls.__name__] = cls()  # instantiate
```

**Result**: `task_registry.tasks` = dict of 201 task instances keyed by class name.

**File**: `MobileWorld/src/mobile_world/tasks/registry.py`

## 2. Device Initialization

```
Agent/Runner                          Server (:6800)
    │                                      │
    ├─ POST /init ────────────────────────>│
    │  {"device": "emulator-5554"}         │
    │                                      ├── ensure_controller(device)
    │                                      │   ├── AndroidController(device)
    │                                      │   │   └── adb shell wm size → (1080, 2400)
    │                                      │   ├── ctr.check_health()
    │                                      │   │   └── adb shell getprop sys.boot_completed → "1"
    │                                      │   └── CONTROLLERS[device] = ctr
    │                                      │
    │<─ {"device": "...", "viewport_size": [1080, 2400]}
```

**File**: `MobileWorld/src/mobile_world/core/server.py` lines 172-195

## 3. Task Initialization

```
Agent/Runner                          Server                              Device
    │                                      │                                 │
    ├─ POST /task/init ──────────────────>│                                 │
    │  {"task_name": "MastodonNewPostTask",│                                │
    │   "req_device": "emulator-5554"}     │                                │
    │                                      ├── task = task_registry.get_task(name)
    │                                      ├── task.initialize_task(controller)
    │                                      │   │
    │                                      │   ├── 1. Load snapshot
    │                                      │   │   └── controller.load_snapshot("init_state")
    │                                      │   │       └── adb emu avd snapshot load init_state
    │                                      │   │       └── sleep(3)
    │                                      │   │       └── controller.home()
    │                                      │   │
    │                                      │   ├── 2. Stop old backends
    │                                      │   │   ├── mastodon.stop_mastodon_backend()
    │                                      │   │   ├── mattermost.stop_mattermost_backend()
    │                                      │   │   ├── clear_config()
    │                                      │   │   └── clear_callback_files()
    │                                      │   │
    │                                      │   ├── 3. Time sync (if Chrome/Maps/MCP)
    │                                      │   │   └── time_sync_to_now()
    │                                      │   │
    │                                      │   ├── 4. Task-specific setup
    │                                      │   │   └── self.initialize_task_hook(controller)
    │                                      │   │       # e.g., start Mastodon backend,
    │                                      │   │       # push files to device,
    │                                      │   │       # inject SMS, set mall config
    │                                      │   │
    │                                      │   ├── 5. User agent setup
    │                                      │   │   └── self.initialize_user_agent_hook(controller)
    │                                      │   │       # Sets controller.user_sys_prompt
    │                                      │   │       # Configures LLM for interactive tasks
    │                                      │   │
    │                                      │   ├── 6. Go home
    │                                      │   │   └── controller.home()
    │                                      │   │       └── adb shell input keyevent KEYCODE_HOME
    │                                      │   │
    │                                      │   └── 7. Reset state
    │                                      │       ├── controller.interaction_cache = ""
    │                                      │       └── self.initialized = True
    │                                      │
    │                                      ├── RUNNING_TASK = task
    │<─ 200 "OK" ─────────────────────────│
```

**File**: `MobileWorld/src/mobile_world/tasks/base.py` lines 105-150

## 4. Agent Execution Loop

```
Agent                    Runner                    Server                  Device
  │                        │                         │                      │
  │                        ├─ GET /screenshot ──────>│                      │
  │                        │   return_b64=true       ├── ctr.get_screenshot()
  │                        │                         │   └── adb exec-out screencap -p
  │                        │<─ {b64_png: "..."} ─────│                      │
  │                        │                         │                      │
  │<─ obs = {screenshot}───│                         │                      │
  │                        │                         │                      │
  │── agent.predict(obs) ──────────────────────────────────────────────────│
  │   → thought, action    │                         │                      │
  │                        │                         │                      │
  │──────────────────────>├─ POST /step ────────────>│                      │
  │   action={             │  {"device": "...",       │                      │
  │     action_type:"click"│   "action": {...}}       │                      │
  │     x: 540, y: 960    │                          ├── dispatch by action_type:
  │   }                    │                          │   CLICK → ctr.tap(x, y)
  │                        │                          │     └── adb shell input tap 540 960
  │                        │                          │   INPUT_TEXT → ctr.text(text)
  │                        │                          │     └── adb shell am broadcast ADB_INPUT_B64
  │                        │                          │   SCROLL → ctr.swipe(direction)
  │                        │                          │     └── adb shell input swipe ...
  │                        │                          │   ANSWER → controller.interaction_cache = text
  │                        │                          │   ASK_USER → call user agent LLM
  │                        │                          │   OPEN_APP → adb shell monkey -p pkg
  │                        │                          │   NAVIGATE_HOME → adb shell input keyevent HOME
  │                        │                          │   NAVIGATE_BACK → adb shell input keyevent BACK
  │                        │<─ {"result": "..."} ─────│                      │
  │                        │                         │                      │
  │                        ├─ GET /screenshot ──────>│ (next observation)   │
  │<─ obs ─────────────────│                         │                      │
  │                        │                         │                      │
  │   [repeat until ANSWER/FINISHED/max_steps]       │                      │
```

**Action types** (21 total): `click`, `double_tap`, `long_press`, `drag`, `input_text`, `keyboard_enter`, `navigate_home`, `navigate_back`, `open_app`, `scroll`, `swipe`, `wait`, `answer`, `finished`, `unknown`, `error_env`, `ask_user`, `mcp`, `status`

**File**: `MobileWorld/src/mobile_world/core/server.py` lines 315-435

## 5. Task Evaluation

```
Agent/Runner                          Server
    │                                      │
    ├─ GET /task/eval ───────────────────>│
    │  {"task_name": "...",               │
    │   "req_device": "..."}              │
    │                                      ├── task = task_registry.get_task(name)
    │                                      ├── task.is_successful(controller)
    │                                      │   │
    │                                      │   │  Verification methods (per task):
    │                                      │   ├── ADB queries
    │                                      │   │   └── adb shell content query --uri content://sms/sent
    │                                      │   ├── SQLite queries
    │                                      │   │   └── adb shell su root sqlite3 events.db "SELECT..."
    │                                      │   ├── PostgreSQL queries
    │                                      │   │   └── psycopg2.connect(host=localhost, port=5432)
    │                                      │   │       SELECT * FROM statuses WHERE ...
    │                                      │   ├── File checks
    │                                      │   │   └── adb shell cat /sdcard/.../sentEmail.json
    │                                      │   ├── interaction_cache
    │                                      │   │   └── controller.interaction_cache == "42"
    │                                      │   └── REST API validation
    │                                      │       └── requests.get(open-meteo API)
    │                                      │
    │                                      │   Returns: (score: float, reason: str)
    │                                      │            score = 0.0 (fail) or 1.0 (pass)
    │                                      │
    │<─ {"score": 1.0, "reason": "Success"}│
```

**Key**: Verification is 100% rule-based. No LLM judge. No screenshots used for eval.

**File**: `MobileWorld/src/mobile_world/core/server.py` lines 516-531

## 6. Task Teardown

```
Agent/Runner                          Server
    │                                      │
    ├─ POST /task/tear_down ─────────────>│
    │  {"task_name": "...",               │
    │   "req_device": "..."}              ├── task.tear_down(controller)
    │                                      │   ├── controller.interaction_cache = ""
    │                                      │   ├── controller.user_sys_prompt = None
    │                                      │   ├── controller.model_config = None
    │                                      │   ├── controller.user_agent_chat_history = []
    │                                      │   └── self.initialized = False
    │                                      │
    │                                      ├── RUNNING_TASK = None
    │<─ 200 "OK" ─────────────────────────│
```

**File**: `MobileWorld/src/mobile_world/tasks/base.py` lines 187-196

## 7. HTTP Endpoints Quick Reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/init` | Initialize device controller |
| GET | `/health` | Check device health |
| GET | `/screenshot` | Capture screenshot (base64 or file) |
| GET | `/xml` | Get UI accessibility tree |
| POST | `/step` | Execute agent action |
| POST | `/sms` | Simulate incoming SMS |
| GET | `/task/list` | List all 201 tasks with tags |
| GET | `/task/goal` | Get task goal text |
| POST | `/task/init` | Initialize task (snapshot + setup) |
| GET | `/task/eval` | Evaluate task (rule-based) |
| POST | `/task/tear_down` | Cleanup after task |
| POST | `/reset` | SkyRL: teardown + init combined |
| POST | `/step_adb` | SkyRL: raw ADB command execution |
| GET | `/deep_health` | SkyRL: emulator responsiveness check |

## 8. Task Definition Format

Each task is a Python class:

```python
# MobileWorld/src/mobile_world/tasks/definitions/mastodon/mastodon_new_post.py

class MastodonNewPostTask(BaseTask):
    goal = "Open Mastodon app and post a new toot with 'Hello from AI agent!'"
    task_tags = {"lang-en"}
    app_names = {"Mastodon"}

    def initialize_task_hook(self, controller):
        mastodon.start_mastodon_backend()  # Docker-in-Docker
        return True

    def is_successful(self, controller):
        toots = mastodon.get_latest_toots_by_username("test", limit=1)
        if toots and "Hello from AI agent!" in toots[0]["text"]:
            return 1.0, "Success"
        return 0.0, "Toot not found"

    def tear_down(self, controller):
        super().tear_down(controller)
        mastodon.stop_mastodon_backend()
```

**Properties**:
- `goal` — natural language instruction shown to the agent
- `task_tags` — `{"lang-en"}`, `{"agent-mcp"}`, `{"agent-user-interaction"}`
- `app_names` — which apps the task involves
- `snapshot_tag` — AVD snapshot name (default: `"init_state"`)

## 9. Key State Variables

| Variable | Location | Purpose |
|----------|----------|---------|
| `task_registry.tasks` | Server global | Dict of all 201 task instances |
| `RUNNING_TASK` | Server global | Currently active task (or None) |
| `CONTROLLERS` | Server global | Cached AndroidController per device |
| `controller.interaction_cache` | AndroidController | Stores agent's answer for info-retrieval tasks |
| `controller.viewport_size` | AndroidController | Screen dimensions (1080, 2400) |
| `task.initialized` | BaseTask | Whether init was called successfully |

## 10. File Locations

| Component | Path |
|-----------|------|
| Server | `MobileWorld/src/mobile_world/core/server.py` |
| Base task class | `MobileWorld/src/mobile_world/tasks/base.py` |
| Task registry | `MobileWorld/src/mobile_world/tasks/registry.py` |
| Task definitions | `MobileWorld/src/mobile_world/tasks/definitions/{category}/*.py` |
| Android controller | `MobileWorld/src/mobile_world/runtime/controller.py` |
| Client library | `MobileWorld/src/mobile_world/runtime/client.py` |
| Evaluation runner | `MobileWorld/src/mobile_world/core/runner.py` |
| SkyRL adapter | `MobileWorld/src/mobile_world/core/skyrl_adapter.py` |
| App helpers | `MobileWorld/src/mobile_world/runtime/app_helpers/{mastodon,mattermost,mall,mail,system}.py` |
| Docker entrypoint | `MobileWorld/docker/entrypoint.sh` |
| Mastodon compose | `MobileWorld/docker/mastodon-docker/docker-compose.yml` |
| Mattermost compose | `MobileWorld/docker/mattermost-docker/docker-compose.yml` |
