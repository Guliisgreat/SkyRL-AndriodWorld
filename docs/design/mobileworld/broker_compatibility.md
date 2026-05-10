# MobileWorld → AndroidWorld Broker Compatibility

## Background

AndroidWorld:2026 uses a broker-based container pool (`pool_broker.py`) with a standard HTTP API: `/acquire`, `/return`, `/status`, `/health`. Each container exposes `/health`, `/reset`, `/exec`, and `/step` endpoints. The broker calls `/reset` on container return to ensure clean state.

MobileWorld's vanilla server (`ghcr.io/tongyi-mai/mobile_world:latest`) was designed for single-container evaluation and lacks the endpoints needed for broker integration. This doc covers what was changed to make MobileWorld containers compatible with the same broker protocol.

## Changes to MobileWorld Server

Only one file was modified: `src/mobile_world/core/server.py`. All changes are additive — no existing endpoints were altered.

### Change 1: `/exec` Endpoint (appended to server.py at image build time)

The vanilla MobileWorld server has no way for CLI agents to execute arbitrary commands. AndroidWorld provides `/exec` for this. We add it via `server_exec_patch.py`, appended to `server.py` during Docker image build.

```python
@app.post("/exec")
def exec_command(req: dict):
    """Execute arbitrary command in the container."""
    command = req.get("command", "")
    result = subprocess.run(command, shell=True, capture_output=True,
                            text=True, timeout=60)
    return {
        "command_output": result.stdout.strip(),
        "reward": 0.0, "terminated": False,
        "truncated": False, "info": {},
    }
```

**Why:** The `mw_env.py` CLI wrapper (used by Claude Code and other agents) sends ADB commands through this endpoint. Without it, agents can't control the phone.

**How applied:** Not committed to MobileWorld repo. Appended at Docker build time:
```dockerfile
COPY server_exec_patch.py /app/service/server_exec_patch.py
RUN cd /app/service && \
    if ! grep -q "/exec" src/mobile_world/core/server.py; then \
        cat server_exec_patch.py >> src/mobile_world/core/server.py; \
    fi
```

### Change 2: `/reset` Endpoint (committed to MobileWorld repo)

The broker needs to fully reset container state between tasks. AndroidWorld containers have `/reset` that loads an emulator snapshot. MobileWorld has three layers of state that need resetting.

```python
@app.post("/reset")
def reset_device(req: TaskOperationRequest):
    """Full state reset between tasks."""
    # 1. Tear down current task (server Python state)
    if RUNNING_TASK is not None:
        RUNNING_TASK.tear_down(controller)
        RUNNING_TASK = None

    # 2. Stop Docker-in-Docker backends
    mattermost.stop_mattermost_backend()
    mastodon.stop_mastodon_backend()
    clear_config()
    clear_callback_files(device)

    # 3. Load emulator snapshot (reverts all Android state)
    controller.load_snapshot("init_state")
    controller.home()

    # 4. Verify health
    healthy = controller.check_health(try_times=3)
    return {"ok": snapshot_ok and healthy, "reset_time_ms": elapsed}
```

**Three layers reset:**

| Layer | What persists | How reset |
|-------|---------------|-----------|
| Server Python | `RUNNING_TASK`, `CONTROLLERS` dict, task registry instances | `tear_down()` + set `RUNNING_TASK = None` |
| Docker-in-Docker | Mastodon/Mattermost PostgreSQL, Redis, Docker volumes | `stop_mastodon_backend()` / `stop_mattermost_backend()` (runs `docker compose down` + deletes data dir) |
| Android emulator | SMS, calendar, contacts, files, settings, app data | `load_snapshot("init_state")` reverts entire filesystem |

**Timing:** ~5 seconds per reset.

### Change 3: `/verify_clean` Endpoint (committed to MobileWorld repo)

Debugging endpoint to check if container state is actually clean after reset.

```python
@app.get("/verify_clean")
def verify_clean(req_device: str = "emulator-5554"):
    issues = []
    if RUNNING_TASK is not None:
        issues.append(f"RUNNING_TASK set: {RUNNING_TASK.name}")
    if controller.interaction_cache:
        issues.append("interaction_cache not empty")
    return {"clean": len(issues) == 0, "issues": issues}
```

### Change 4: `DEFAULT_DEVICE` from Environment (committed to MobileWorld repo)

AndroidWorld containers derive the emulator device serial from `EMULATOR_PORT` env var (for host-network multi-container setups). Added the same pattern:

```python
_EMULATOR_PORT = int(os.environ.get("EMULATOR_PORT", "5554"))
DEFAULT_DEVICE = f"emulator-{_EMULATOR_PORT}"
```

## Endpoint Comparison

| Endpoint | AndroidWorld | MobileWorld (vanilla) | MobileWorld (patched) |
|----------|-------------|----------------------|----------------------|
| `GET /health` | Yes | Yes | Yes |
| `POST /reset` | Yes | No | **Yes (added)** |
| `POST /exec` | Yes | No | **Yes (added)** |
| `POST /step` | Yes | Yes | Yes |
| `GET /xml` | Yes (a11y tree) | Yes | Yes |
| `GET /screenshot` | Yes | Yes | Yes |
| `POST /task/init` | N/A | Yes | Yes |
| `GET /task/eval` | N/A | Yes | Yes |
| `POST /task/tear_down` | N/A | Yes | Yes |
| `GET /verify_clean` | No | No | **Yes (added)** |

## Broker Compatibility

The MobileWorld broker (`mw_pool_broker.py`) follows the same protocol as AndroidWorld's `pool_broker.py`:

| API | Request | Response |
|-----|---------|----------|
| `POST /acquire` | `{pid, timeout}` | `{env_id, server_port, device_id, server_url}` |
| `POST /return` | `{env_id, healthy}` | OK (triggers `/reset` on container) |
| `GET /status` | — | `{total, idle, leased, containers: [...]}` |
| `GET /health` | — | `{ok: true}` |

The key difference: `mw_pool_broker.py` calls `/reset` on container return (reset-on-return), while AndroidWorld's `pool_broker.py` calls `/reset` on container acquire (reset-on-acquire). Both achieve the same result — clean state before next task.

## How to Build the Docker Image

```bash
# Method 1: Patch existing image (fast, ~1s)
cat << 'DOCKERFILE' > /tmp/mw_broker.Dockerfile
FROM ghcr.io/tongyi-mai/mobile_world:latest

# Add patched server.py with /reset and /verify_clean
COPY server.py /app/service/src/mobile_world/core/server.py

# Add /exec endpoint
COPY server_exec_patch.py /app/service/server_exec_patch.py
RUN cd /app/service && \
    if ! grep -q "/exec" src/mobile_world/core/server.py; then \
        cat server_exec_patch.py >> src/mobile_world/core/server.py; \
    fi
DOCKERFILE

cp MobileWorld/src/mobile_world/core/server.py /tmp/server.py
cp harbor/adapters/mobileworld/template/environment/server_exec_patch.py /tmp/
docker build -t mobile_world:reset -f /tmp/mw_broker.Dockerfile /tmp/

# Method 2: Use MobileWorld's update Dockerfile (if available)
cd MobileWorld
docker build -t mobile_world:reset -f docker/Dockerfile.update .
```

## How to Run with Broker

```bash
# 1. Start N containers (one per port)
for i in $(seq 0 15); do
  docker run -d --name "mw-broker-$i" --privileged --device=/dev/kvm \
    -p $((6804+i)):6800 \
    mobile_world:reset \
    tail -f /var/log/emulator.log /var/log/server.log
done

# 2. Wait for emulators to boot (~2.5 min)
sleep 150

# 3. Reset all containers (triggers device detection)
for i in $(seq 0 15); do
  curl -s -X POST http://localhost:$((6804+i))/reset \
    -H "Content-Type: application/json" \
    -d '{"task_name":"_reset","req_device":"emulator-5554"}'
done

# 4. Start broker
cd skyrl-agent
PYTHONPATH=. python -m skyrl_agent.runtime.android.mw_pool_broker \
  --containers "$(for i in $(seq 0 15); do \
    echo -n "http://localhost:$((6804+i))=emulator-5554,"; \
  done | sed 's/,$//')" \
  --port 9400

# 5. Run experiments
python examples/run_mobileworld/claude_code_cli_agent_broker_mw.py \
  --data data/mobileworld/gui_only_tasks.jsonl \
  --broker-url http://localhost:9400 \
  --pool-size 8 \
  --model claude-sonnet-4-6 \
  --max-turns 30 \
  --prompt mw_adb_oracle
```

## Known Limitations

1. **Emulator detection race condition** — MobileWorld server starts before emulator finishes booting, caches empty device list. Fix: call `/reset` after boot, which triggers `ensure_controller()` to detect the emulator.

2. **Stale task instances** — Some task verifiers compute dates in `__init__()` (run once at server startup). If containers run for days, these dates become stale. Fix: restart the server or container periodically.

3. **No auto-scaling** — Unlike AndroidWorld's broker which creates containers on demand, `mw_pool_broker.py` requires pre-created containers. Pool size is fixed at startup.

4. **`/exec` quoting** — Commands with nested single quotes (SQL INSERTs with string values) fail through the `/exec` → `adb shell` → `su root` → `sqlite3` chain. Workaround: write SQL to a file on device, then execute via shell script.
