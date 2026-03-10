# Parallel Claude Code CLI with Broker

**Date:** 2026-03-09
**Branch:** `feat/cc-tune-claude-agent-sdk`
**Status:** Proposed

## 1. Goal

Run `run_claude_cli.py` against all 71 tasks in parallel using the existing container pool broker. Currently it runs sequentially against a single container — ~3-5 min/task × 71 = ~4-6 hours. With N parallel workers, that drops to ~4-6 hours / N.

## 2. Current State

**`run_claude_cli.py`** (sequential, single container):
```
for task in tasks:
    reset(container_url, task)
    claude -p "..." --allowedTools "Bash(command:*)"
    read state file → reward
```

**Broker** (`pool_broker.py`, FastAPI server):
- Manages a pool of Docker containers
- HTTP API: `POST /acquire` → get a container, `POST /return` → give it back
- Health monitoring, auto-replacement, snapshot restore on return
- Already battle-tested with the Claude SDK runner and VLM training

## 3. Design

### Minimal change: add `--broker-url` and `--pool-size` to `run_claude_cli.py`

```
                    run_claude_cli.py
                    ┌─────────────────┐
                    │  Load tasks      │
                    │  Start N workers │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         Worker 1       Worker 2       Worker N
              │              │              │
              ▼              ▼              ▼
     POST /acquire    POST /acquire   POST /acquire
         broker           broker          broker
              │              │              │
              ▼              ▼              ▼
     reset container  reset container reset container
     claude -p "..."  claude -p "..." claude -p "..."
     read state       read state      read state
              │              │              │
              ▼              ▼              ▼
     POST /return     POST /return    POST /return
         broker           broker          broker
```

Each worker:
1. Pulls next task from a shared queue
2. `POST /acquire` → gets `{server_port, env_id}` → `container_url = http://localhost:{server_port}`
3. Runs `run_one_task(task, container_url, ...)` (existing function, unchanged)
4. `POST /return {env_id, healthy}` → broker restores snapshot, makes container available
5. Writes result to thread-safe output
6. Repeats until queue empty

### What changes in `run_claude_cli.py`

| Area | Current | New |
|------|---------|-----|
| CLI args | `--container-url` (single URL) | Add `--broker-url`, `--pool-size` |
| Execution | Sequential `for` loop | `concurrent.futures.ThreadPoolExecutor` with N workers |
| Container mgmt | Fixed URL | Acquire/return per task via broker HTTP API |
| Output | Single writer | Thread-locked JSONL writer |
| Health check | Per-task against single container | Broker handles health; worker retries on dead container |

### What stays the same

- `run_one_task()` — unchanged (takes a `container_url`, runs claude CLI, reads state)
- `SYSTEM_PROMPT` — unchanged
- `android_env.py` — unchanged
- State file mechanism — unchanged (each task gets its own temp file)
- Single-container mode — still works with `--container-url` (no broker)

## 4. Implementation

### New CLI args
```
--broker-url URL      Broker HTTP URL (e.g., http://localhost:9100)
--pool-size N         Number of parallel workers (default: 8)
```

Mutually exclusive with `--container-url`. If `--broker-url` given, use parallel mode. If `--container-url` given, use sequential mode (existing behavior).

### Worker function
```python
def worker(task_queue, broker_url, model, max_turns, results, lock):
    while True:
        task_def = task_queue.get()  # blocks until available
        if task_def is None:
            break

        # Acquire container from broker
        container = acquire(broker_url, timeout=300)
        container_url = f"http://localhost:{container['server_port']}"

        try:
            result = run_one_task(task_def, container_url, model, max_turns)
        except Exception as e:
            result = {"task_id": task_def["task_id"], "reward": 0.0, "error": str(e)}
        finally:
            # Return container to broker (healthy unless exception)
            release(broker_url, container["env_id"], healthy=True)

        with lock:
            results.append(result)
            # Write to JSONL
```

### Broker interaction (stdlib only)
```python
def acquire(broker_url, timeout=300):
    """POST /acquire → {env_id, server_port, ...}"""
    return http_post(f"{broker_url}/acquire", {"pid": os.getpid(), "timeout": timeout})

def release(broker_url, env_id, healthy=True):
    """POST /return → broker restores snapshot, marks container idle"""
    return http_post(f"{broker_url}/return", {"env_id": env_id, "healthy": healthy})
```

### Thread safety
- `task_queue`: `queue.Queue` (thread-safe by default)
- Output file: protected by `threading.Lock`
- State files: each task gets unique tempfile (no conflicts)
- `claude` CLI subprocesses: independent processes, no shared state

### Error handling
- Broker unreachable → retry 3x with backoff, then skip task
- Container dead during task → `run_one_task` returns with error, return container as unhealthy
- Claude CLI timeout → captured by existing `subprocess.run(timeout=900)`

## 5. Usage

### Start broker (once)
```bash
python -m skyrl_agent.runtime.android.pool_broker \
    --pool-size 16 \
    --docker-image androidworld:v9 \
    --port 9100 \
    --parallel 4
```

### Run all 71 tasks with 16 parallel workers
```bash
python run_claude_cli.py \
    --data ../../data/androidworld_original/val_data_seed7_no_gui.jsonl \
    --broker-url http://localhost:9100 \
    --pool-size 16 \
    --model claude-opus-4-6 \
    --max-turns 30 \
    --output results/ClaudeCodeCLI_opus46_260309_1500/results.jsonl
```

### Run sequentially (existing mode, unchanged)
```bash
python run_claude_cli.py \
    --data ... \
    --container-url http://localhost:5800 \
    --output results.jsonl
```

## 6. Resource Estimates

- 16 containers × ~30 GB RAM each ≈ 480 GB (machine has 2 TB)
- 16 parallel `claude` CLI processes — lightweight (API calls, no GPU)
- ~71 tasks / 16 workers × ~4 min/task ≈ ~18 min total
- API cost: ~71 × $0.10-0.50 ≈ $7-35

## 7. Output Format

Same JSONL format as current, plus output dir follows naming convention:
```
results/ClaudeCodeCLI_opus46_{yymmdd}_{HHMM}/
├── results.jsonl          # per-task results
└── summary.json           # aggregate metrics
```

## 8. Risks

| Risk | Mitigation |
|------|-----------|
| Machine overloaded with 16 containers | Start with 8, scale up. Monitor with `docker stats`. |
| Broker crash mid-run | Workers detect acquire failure, log error, skip task. Results already flushed to disk. |
| Claude API rate limits with 16 parallel | Anthropic rate limits are generous. If hit, subprocess blocks naturally. |
| State file conflicts | Each task gets unique tempfile — no conflicts possible. |
