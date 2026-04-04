# MobileWorld × Harbor Integration Design

**Date**: 2026-04-01
**Status**: Proposal
**Author**: Claude Code

---

## 1. Motivation

MobileWorld is a 201-task benchmark for evaluating AI agents on mobile device tasks (20 apps including Mastodon, Mattermost, Mall, Calendar, Gmail). The current evaluation infrastructure has persistent issues:

- **State accumulation**: MobileWorld server's Python task objects persist in memory across inits
- **Docker-in-docker leakage**: Mastodon/Mattermost backends not fully reset between tasks
- **Timing fragility**: Parallel container reuse causes race conditions
- **No standardized trajectory format**: Custom ATIF generation per runner

Harbor solves all of these by design: **fresh container per task, standard ATIF output, built-in parallel execution, and deterministic verification**.

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│                    Harbor Framework                      │
│                                                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────┐   │
│  │  harbor   │──▶│  Trial   │──▶│  MobileWorld     │   │
│  │  run CLI  │   │  Queue   │   │  Docker Env      │   │
│  └──────────┘   └──────────┘   │  (fresh per task) │   │
│                                 │                    │   │
│                                 │  ┌──────────────┐ │   │
│                                 │  │ Android      │ │   │
│                                 │  │ Emulator     │ │   │
│                                 │  ├──────────────┤ │   │
│                                 │  │ MW Server    │ │   │
│                                 │  │ + /exec API  │ │   │
│                                 │  ├──────────────┤ │   │
│                                 │  │ Mastodon     │ │   │
│                                 │  │ (docker-in-  │ │   │
│                                 │  │  docker)     │ │   │
│                                 │  ├──────────────┤ │   │
│                                 │  │ Mattermost   │ │   │
│                                 │  │ (docker-in-  │ │   │
│                                 │  │  docker)     │ │   │
│                                 │  └──────────────┘ │   │
│                                 └──────────────────┘   │
│                                                          │
│  Agent Options:                                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────────┐   │
│  │ claude-code│  │ mw-cli-   │  │ mw-gui-agent │   │
│  │ (built-in) │  │ agent     │  │ (UI-TARS/T3A)│   │
│  └────────────┘  └────────────┘  └────────────────┘   │
│                                                          │
│  Verifier: test.sh → /task/eval → reward.txt            │
└────────────────────────────────────────────────────────┘
```

---

## 3. Adapter Design: `adapters/mobileworld/`

### 3.1 Directory Structure

```
adapters/mobileworld/
├── adapter.py              # Main: MobileWorldAdapter class
├── run_adapter.py          # CLI: python run_adapter.py --mw-repo /path/to/MobileWorld
├── README.md
├── pyproject.toml
├── template/
│   ├── task.toml           # Base config template
│   ├── instruction.md      # "{{ goal }}" placeholder
│   ├── environment/
│   │   ├── docker-compose.yaml   # Compose for MW container + volumes
│   │   └── Dockerfile            # (optional, if extending base image)
│   ├── tests/
│   │   ├── test.sh               # Calls /task/eval, writes reward.txt
│   │   └── eval_config.json      # Task name, device ID
│   └── solution/
│       └── solve.sh              # Oracle GT commands (for OracleAgent)
└── mw_env.py → symlink to skyrl_agent/agents/mobileworld/claude_sdk/mw_env.py
```

### 3.2 Adapter Class

```python
class MobileWorldAdapter:
    """Convert MobileWorld tasks to Harbor format."""

    NAME = "mobileworld"

    def __init__(self, task_dir: Path, mw_repo: Path, task_filter: str = "gui_only"):
        self.task_dir = task_dir
        self.mw_repo = mw_repo
        self.task_filter = task_filter  # "gui_only", "all", "cli_solvable"

    def get_all_ids(self) -> list[str]:
        """Return all task names from MobileWorld."""
        # Parse task definitions from mw_repo/src/mobile_world/tasks/definitions/
        ...

    def generate_task(self, task_name: str) -> None:
        """Generate a Harbor task directory for one MobileWorld task."""
        output_dir = self.task_dir / f"mw-{task_name.lower()}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy template
        self._copy_template(output_dir)

        # 2. Write instruction.md with the task goal
        goal = self._extract_goal(task_name)
        (output_dir / "instruction.md").write_text(goal)

        # 3. Write eval_config.json (task name for verifier)
        config = {"task_name": task_name, "device_id": "emulator-5554"}
        (output_dir / "tests" / "eval_config.json").write_text(json.dumps(config))

        # 4. Write solution/solve.sh with GT commands (for OracleAgent)
        gt_commands = self._get_gt_commands(task_name)
        (output_dir / "solution" / "solve.sh").write_text(gt_commands)

        # 5. Customize task.toml based on task category
        self._customize_config(output_dir, task_name)
```

### 3.3 Task Configuration (`task.toml`)

```toml
version = "1.0"

[metadata]
author_name = "MobileWorld Benchmark"
category = "mobile-agent"
tags = "android,mobileworld,{{ category }}"

[verifier]
timeout_sec = 120

[agent]
timeout_sec = 900   # 15 min for complex tasks
user = "root"

[environment]
build_timeout_sec = 300
docker_image = "mobile_world:harbor"   # Pre-built image with /exec endpoint
cpus = 4
memory_mb = 8192
storage_mb = 20480
allow_internet = true

[environment.env]
# Template variables resolved at runtime
MW_SERVER_URL = "http://localhost:6800"
MW_ADB_SERIAL = "localhost:5556"
MW_DEVICE_ID = "emulator-5554"
MW_STATE_FILE = "/logs/agent/state.json"
MW_DISABLE_TREE = "${MW_DISABLE_TREE:-1}"
MW_TASK_NAME = "{{ task_name }}"
```

---

## 4. Docker Environment

### 4.1 Base Image: `mobile_world:harbor`

Extends the MobileWorld image with Harbor requirements:

```dockerfile
FROM ghcr.io/tongyi-mai/mobile_world:latest

# Harbor requirements
RUN mkdir -p /logs/agent /logs/verifier /logs/artifacts /tests /solution

# Ensure /exec endpoint is available in MW server
# (patch server if vanilla image doesn't have it)
COPY mw_server_patch.py /app/service/

# Copy mw_env.py for CLI agents
COPY mw_env.py /usr/local/bin/mw_env.py
RUN chmod +x /usr/local/bin/mw_env.py

# Entrypoint: start supervisord (emulator + MW server), then sleep
ENTRYPOINT ["/usr/bin/supervisord", "-n"]
```

### 4.2 Docker Compose

```yaml
services:
  main:
    image: mobile_world:harbor
    privileged: true          # Required for Android emulator + docker-in-docker
    command: ["sh", "-c", "sleep infinity"]
    environment:
      - MW_TASK_NAME=${MW_TASK_NAME}
      - MW_DEVICE_ID=${MW_DEVICE_ID:-emulator-5554}
    volumes:
      - ${HOST_VERIFIER_LOGS_PATH}:${ENV_VERIFIER_LOGS_PATH}
      - ${HOST_AGENT_LOGS_PATH}:${ENV_AGENT_LOGS_PATH}
      - ${HOST_ARTIFACTS_PATH}:${ENV_ARTIFACTS_PATH}
    deploy:
      resources:
        limits:
          cpus: ${CPUS:-4}
          memory: ${MEMORY:-8G}
    # KVM for emulator acceleration
    devices:
      - /dev/kvm:/dev/kvm
```

### 4.3 Container Lifecycle (Harbor-managed)

```
1. Harbor creates fresh container from mobile_world:harbor
2. Supervisord starts: emulator boots, MW server starts (~60s)
3. Harbor uploads /tests/ (test.sh, eval_config.json)
4. Harbor uploads /solution/ (for OracleAgent)
5. Agent runs:
   a. CLI agent: executes mw_env.py commands via Bash tool
   b. GUI agent: sends ADB touch/swipe commands
6. test.sh runs: calls /task/eval on MW server, writes reward.txt
7. Harbor downloads /logs/, stops+deletes container
```

**Key benefit**: Fresh container = zero state leakage. Every task starts from a clean image with pristine Mastodon/Mattermost data.

---

## 5. Verifier: `tests/test.sh`

```bash
#!/bin/bash
set -e
mkdir -p /logs/verifier

# Read task config
TASK_NAME=$(python3 -c "import json; print(json.load(open('/tests/eval_config.json'))['task_name'])")
DEVICE_ID=$(python3 -c "import json; print(json.load(open('/tests/eval_config.json'))['device_id'])")

# Wait for MW server to be ready
for i in $(seq 1 30); do
  if curl -sf http://localhost:6800/health > /dev/null 2>&1; then
    break
  fi
  sleep 2
done

# Initialize task (snapshot restore + backend startup)
curl -s -X POST http://localhost:6800/task/init \
  -H "Content-Type: application/json" \
  -d "{\"task_name\": \"$TASK_NAME\", \"req_device\": \"$DEVICE_ID\"}"

# Wait for backends (Mastodon/Mattermost need ~30s after init)
sleep 30

# ===== Agent execution happens here (managed by Harbor) =====
# Harbor calls agent.run() which uses mw_env.py or GUI actions

# After agent finishes, evaluate
RESULT=$(curl -s -X GET http://localhost:6800/task/eval \
  -H "Content-Type: application/json" \
  -d "{\"task_name\": \"$TASK_NAME\", \"req_device\": \"$DEVICE_ID\"}")

SCORE=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('score', 0.0))")
REASON=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('reason', ''))")

echo "Score: $SCORE"
echo "Reason: $REASON"

# Write reward
echo "$SCORE" > /logs/verifier/reward.txt
echo "{\"score\": $SCORE, \"reason\": \"$REASON\"}" > /logs/verifier/reward.json

# Teardown
curl -s -X POST http://localhost:6800/task/tear_down \
  -H "Content-Type: application/json" \
  -d "{\"task_name\": \"$TASK_NAME\", \"req_device\": \"$DEVICE_ID\"}" || true
```

**Important**: The test.sh handles init + eval + teardown. The agent only runs commands between init and eval. Harbor's trial orchestrator calls test.sh AFTER the agent finishes.

Actually, there's a subtlety: Harbor runs test.sh AFTER the agent. But MobileWorld needs task/init BEFORE the agent runs. This requires splitting the lifecycle:

### 5.1 Revised Lifecycle with Setup Script

```
tests/
├── setup.sh        # Called BEFORE agent: task/init + wait
├── test.sh         # Called AFTER agent: task/eval + reward
└── eval_config.json
```

Harbor doesn't have a built-in "setup before agent" hook. Two options:

**Option A**: Agent's `setup()` method calls task/init:
```python
async def setup(self, environment):
    # Initialize MobileWorld task
    await environment.exec(
        f"curl -s -X POST http://localhost:6800/task/init "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"task_name\": \"{self.task_name}\", \"req_device\": \"emulator-5554\"}}'")
    await asyncio.sleep(30)  # Wait for backends
```

**Option B**: Embed init in the entrypoint/Dockerfile:
```dockerfile
# Auto-init on container start
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

```bash
#!/bin/bash
# Start emulator + MW server
/usr/bin/supervisord -n &
sleep 60  # Wait for boot

# Auto-init task
TASK_NAME=$(cat /tests/eval_config.json | python3 -c "import json,sys; print(json.load(sys.stdin)['task_name'])")
curl -s -X POST http://localhost:6800/task/init \
  -H "Content-Type: application/json" \
  -d "{\"task_name\": \"$TASK_NAME\", \"req_device\": \"emulator-5554\"}"
sleep 30  # Wait for backends

# Signal ready
touch /tmp/mw_ready
sleep infinity
```

**Recommendation**: Option A (agent setup) is cleaner and more Harbor-idiomatic.

---

## 6. Agent Implementations

### 6.1 CLI Agent (Claude Code / Terminal Agent)

Uses `claude-code` built-in agent with MobileWorld skills:

```bash
harbor run \
  --dataset mobileworld@1.0 \
  --agent claude-code \
  --model anthropic/claude-sonnet-4-6 \
  --ae MW_DISABLE_TREE=1 \
  --n-concurrent 8
```

The agent has access to `mw_env.py` as a Bash tool with 8 subcommands:

| Subcommand | Purpose |
|---|---|
| `adb` | Android device shell commands |
| `sql` | SQLite queries on device databases |
| `http` | REST API calls (Mastodon, external) |
| `exec` | Shell commands inside container (psql, server filesystem) |
| `read-file` | Read files from device |
| `write-file` | Write files to device |
| `find-files` | Search files on device |
| `finish` | Submit answer / signal completion |

**Agent prompt** (via instruction.md or system prompt):
```
You are controlling an Android phone via terminal commands.
Use `python /usr/local/bin/mw_env.py <subcommand>` to interact with the device.
Available subcommands: adb, sql, http, exec, read-file, write-file, find-files, finish.

When done, call: python /usr/local/bin/mw_env.py finish --status complete --description "<result>"
```

### 6.2 GUI Agent (UI-TARS / T3A / Custom Vision Agent)

For GUI agents that interact via screenshots + ADB touch/swipe:

```python
# Custom agent: agents/installed/mw_gui_agent.py
class MobileWorldGUIAgent(BaseInstalledAgent):
    """GUI agent for MobileWorld — uses screenshots + accessibility tree."""

    SUPPORTS_ATIF = True

    @staticmethod
    def name() -> str:
        return "mw-gui-agent"

    async def setup(self, environment: BaseEnvironment) -> None:
        # Install agent dependencies
        await environment.exec("pip install pillow requests")
        # Init MobileWorld task
        task_name = os.environ.get("MW_TASK_NAME", "")
        await environment.exec(
            f"curl -s -X POST http://localhost:6800/task/init "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"task_name\": \"{task_name}\", \"req_device\": \"emulator-5554\"}}'")
        await asyncio.sleep(30)

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        # GUI agent loop:
        # 1. Get screenshot: GET /screenshot
        # 2. Get accessibility tree: GET /xml
        # 3. Send to VLM (GPT-4o, Qwen-VL, UI-TARS)
        # 4. Parse action (tap, swipe, type, scroll)
        # 5. Execute via adb: POST /exec {"command": "adb shell input tap X Y"}
        # 6. Repeat until done or max steps
        ...
```

### 6.3 Oracle Agent (Ground Truth)

Uses Harbor's built-in `oracle` agent with `solve.sh`:

```bash
harbor run \
  --dataset mobileworld@1.0 \
  --agent oracle \
  --n-concurrent 8
```

`solution/solve.sh` contains the verified GT commands:
```bash
#!/bin/bash
# CheckConferenceAndSendSmsTask1 — Oracle Ground Truth
python /usr/local/bin/mw_env.py sql /data/data/org.fossify.calendar/databases/events.db \
  "SELECT title,start_ts,end_ts FROM events WHERE title LIKE '%Paris%' ORDER BY start_ts"
# ... (remaining GT commands from the 88 verified tasks)
```

---

## 7. Task Categories and Resource Profiles

| Category | Tasks | CPU | Memory | Timeout | Needs Docker-in-Docker |
|----------|-------|-----|--------|---------|----------------------|
| Calendar | 7 | 2 | 4GB | 300s | No |
| Gmail | 15 | 2 | 4GB | 300s | No |
| Chrome/Web | 2 | 2 | 4GB | 300s | No (needs internet) |
| Mall | 7 | 2 | 4GB | 300s | No |
| Map | 3 | 2 | 4GB | 300s | No |
| Messages | 1 | 2 | 4GB | 300s | No |
| Native | 7 | 2 | 4GB | 300s | No |
| Mastodon | 32 | 4 | 8GB | 600s | Yes (6 sub-containers) |
| Mattermost | 15 | 4 | 8GB | 600s | Yes (2 sub-containers) |
| PDF/OCR | 8 | 2 | 4GB | 300s | No |

Mastodon/Mattermost tasks need `privileged: true` for docker-in-docker.

---

## 8. ATIF Trajectory Generation

CLI agents that use `mw_env.py` automatically record steps in the state file. After agent execution, convert to ATIF:

```python
# In test.sh or post-agent hook:
python3 -c "
import json
from harbor.models.trajectories import Trajectory, Step, ToolCall, Observation

state = json.load(open('/logs/agent/state.json'))
steps = [
    Step(step_id=1, source='system', message='[MobileWorld CLI Agent]'),
    Step(step_id=2, source='user', message=open('/tests/instruction.md').read()),
]
for i, rec in enumerate(state['step_records']):
    steps.append(Step(
        step_id=i+3, source='agent',
        message=rec.get('thought', ''),
        tool_calls=[ToolCall(
            tool_call_id=f'call_{i}',
            function_name='Bash',
            arguments={'command': f'python mw_env.py {rec[\"action_type\"]} ...'}
        )],
        observation=Observation(results=[{
            'source_call_id': f'call_{i}',
            'content': rec.get('command_output', '')
        }])
    ))

traj = Trajectory(schema_version='ATIF-v1.6', session_id='...', agent={...}, steps=steps)
Path('/logs/agent/trajectory.json').write_text(traj.model_dump_json(indent=2))
"
```

---

## 9. Testing Plan

### 9.1 Unit Tests

```bash
# Test adapter generates correct task directories
uv run pytest tests/unit/test_mobileworld_adapter.py

# Test task.toml validation
uv run pytest tests/unit/test_mobileworld_task_config.py
```

### 9.2 Integration Tests (Single Task)

```bash
# Build the Harbor MobileWorld image
docker build -t mobile_world:harbor -f adapters/mobileworld/Dockerfile .

# Generate tasks
python adapters/mobileworld/run_adapter.py \
  --mw-repo /path/to/MobileWorld \
  --output-dir ./datasets/mobileworld \
  --filter gui_only

# Run single task with oracle agent
harbor run \
  --task ./datasets/mobileworld/mw-mastodonnewtask \
  --agent oracle \
  --environment docker
```

### 9.3 Smoke Test (5 Tasks, All Categories)

```bash
harbor run \
  --dataset mobileworld@1.0 \
  --agent claude-code \
  --model anthropic/claude-sonnet-4-6 \
  --n-concurrent 5 \
  --filter "mw-acceptmeetingtask,mw-mastodonnewtask,mw-checkpuchaseditem,mw-countfilelinestask,mw-mattermostemailtask"
```

### 9.4 Full Benchmark (93 Tasks)

```bash
# CLI agent
harbor run \
  --dataset mobileworld@1.0 \
  --agent claude-code \
  --model anthropic/claude-sonnet-4-6 \
  --ae MW_DISABLE_TREE=1 \
  --n-concurrent 8

# GUI agent
harbor run \
  --dataset mobileworld@1.0 \
  --agent mw-gui-agent \
  --model openai/gpt-4o \
  --n-concurrent 4

# Oracle (ground truth verification)
harbor run \
  --dataset mobileworld@1.0 \
  --agent oracle \
  --n-concurrent 12
```

### 9.5 Verify Zero State Leakage

```bash
# Run the same task 3 times — should get identical results
harbor run \
  --task ./datasets/mobileworld/mw-invoicereceiptcopyaskusertask \
  --agent oracle \
  --n-trials 3

# All 3 trials should PASS (no state accumulation)
harbor trials list --job-dir ./jobs/latest/ --format json | jq '.[] | .reward'
# Expected: 1.0, 1.0, 1.0
```

---

## 10. Migration Path

### Phase 1: Adapter + Oracle (1-2 days)
1. Create `adapters/mobileworld/` with adapter class
2. Build `mobile_world:harbor` Docker image
3. Generate 93 task directories
4. Write `test.sh` verifier
5. Write `solve.sh` for all 88 verified GT tasks
6. Run oracle agent → verify 88/93 pass

### Phase 2: CLI Agent Integration (1 day)
1. Package `mw_env.py` in the Harbor image
2. Write agent prompt/instruction template
3. Test with `claude-code` agent
4. Compare results with current broker-based evaluation

### Phase 3: GUI Agent Integration (2-3 days)
1. Implement `MobileWorldGUIAgent` class
2. Add screenshot/XML observation pipeline
3. Support ADB touch/swipe action space
4. Test with UI-TARS and T3A models

### Phase 4: Registry Publishing (1 day)
1. Add `mobileworld` to Harbor registry
2. Publish dataset: `harbor publish ./datasets/mobileworld`
3. Document usage in README

---

## 11. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Fresh container per task | Yes | Eliminates ALL state leakage issues |
| Pre-built image | `mobile_world:harbor` | Avoid 3-min build per task; boot from snapshot |
| Agent init via setup() | Not entrypoint | More Harbor-idiomatic, allows agent to control timing |
| Verifier via test.sh | Calls `/task/eval` | Reuses MobileWorld's existing rule-based verifiers |
| `mw_env.py` in image | Copied to `/usr/local/bin/` | Agent can use via `Bash(command:*)` tool |
| Docker-in-docker | `privileged: true` | Required for Mastodon/Mattermost backends |
| ATIF generation | Post-agent conversion from state.json | Clean separation of agent execution and trajectory recording |

---

## 12. Open Questions

1. **Container boot time**: MobileWorld emulator takes ~60s to boot. Can we use pre-booted snapshots to reduce this?
2. **Image size**: The MobileWorld image is ~15GB. Harbor's Docker environment needs fast pull/start.
3. **KVM access**: Emulator acceleration requires `/dev/kvm`. Not available on all cloud providers (Modal, E2B may not support).
4. **GPU for GUI agents**: Vision models (UI-TARS) need GPU. Harbor's Docker environment supports `gpus` config but needs NVIDIA runtime.
5. **Mastodon boot time**: Docker-compose inside the container adds another ~30s. Total cold start: ~90s per task.
