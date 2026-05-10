# Container Pool Broker

How Android emulator containers are managed for evaluation and training, and
how to start / talk to / debug the pool broker.

> Last sync: post-`237ab9e0` (broker code lives in `eval-runners/common/runtime/`).

---

## 1. Modes at a glance

| Mode | Who owns containers | When to use |
|---|---|---|
| **A — Local** (`ContainerManager`) | Experiment process | One-off training or eval; no other process needs the pool |
| **B — Broker** (`pool_broker.py` + `BrokerContainerManager`) | A long-lived FastAPI server | Multi-experiment, GUI-vs-CLI sweeps, anything where you don't want to pay container startup cost on every run |

Both modes expose the **same** `allocate_container / release_container /
get_pool_status` Python interface, so the dispatcher and runner code is
identical. Mode B is selected by setting `env.broker_url` in the YAML or by
passing `--broker-url` to an `eval-runners/benchmarks/*/run_*.py` script.

```
MODE A — Local Container Management
====================================

  ┌──────────────────────────────────────────────┐
  │  Experiment process                          │
  │                                              │
  │  AndroidTask.initialize_runtime()            │
  │       │                                      │
  │       ▼                                      │
  │  ContainerManager  (eval-runners/common/     │
  │   ├── create_pool_parallel()  (slow ~5 min)  │
  │   ├── HealthMonitor (background)             │
  │   ├── allocate_container()                   │
  │   └── release_container()                    │
  │       │                                      │
  │       ▼                                      │
  │  Docker containers (created+destroyed        │
  │  with each experiment)                       │
  └──────────────────────────────────────────────┘


MODE B — Broker-Managed Container Pool
========================================

  ┌──────────────────┐    HTTP     ┌──────────────────────────┐
  │ Experiment 1     │◄──────────►│  pool_broker.py          │
  │ BrokerContainer- │            │                          │
  │ Manager          │            │  ContainerPoolBroker     │
  └──────────────────┘            │   ├── /acquire           │
                                  │   ├── /return → /reset   │
  ┌──────────────────┐            │   ├── health loop        │
  │ Experiment 2     │◄──────────►│   ├── GC loop            │
  └──────────────────┘            │   ├── reconcile loop     │
                                  │   └── container pool     │
  ┌──────────────────┐            │       ├── env0 .. envN   │
  │ Experiment N     │◄──────────►│  Containers persist      │
  └──────────────────┘            │  across experiments      │
                                  └──────────────────────────┘
```

---

## 2. Brokers shipped today

There are three broker entry points, all under `eval-runners/common/runtime/`,
all speaking the same HTTP API:

| Broker | Backs | Behaviour |
|---|---|---|
| `pool_broker.py` | AndroidWorld (`androidworld:2026*` images) | **Creates** containers from a Docker image at startup; runs health/GC/reconcile loops; calls `/reset` on `/return` |
| `mw_pool_broker.py` | MobileWorld (pre-existing containers) | **Adopts** already-running containers by host:port; same `/acquire`/`/return` API; calls `/reset` on `/return` |
| `androidlab_broker.py` | AndroidLab | AndroidLab-specific lifecycle |

All three implement:

| Endpoint | Body / Response |
|---|---|
| `POST /acquire` | `{pid, timeout}` → `{env_id, server_url, server_port, emulator_port, grpc_port, host, container_id}` |
| `POST /return`  | `{env_id, healthy}` → `{status: "returned"}` (broker invokes `/reset` on the container) |
| `GET  /status`  | `{total, idle, leased, pool_initializing, ...}` |
| `GET  /health`  | `{status, uptime, pool_ready, pool_target, pool_initializing}` |

---

## 3. Quick start (Mode B — preferred for evaluation)

### 3.1 Start the AndroidWorld broker

```bash
cd /path/to/SkyRL-AndroidWorld

PYTHONPATH=eval-runners/common/runtime:. \
python eval-runners/common/runtime/pool_broker.py \
    --pool-size 16 \
    --docker-image androidworld:2026plusswipe \
    --port 9400 \
    --base-env-id 700 \
    --parallel 4
```

Watch the log until you see `pool_initializing=False` in `GET /health` —
container creation is parallelised by `--parallel` but each emulator still
needs ~30–60 s to boot.

The flags that matter most:

| Flag | Default | Notes |
|---|---|---|
| `--pool-size` | 24 | Total containers the broker manages |
| `--docker-image` | `androidworld:v8` | Use `androidworld:2026plusswipe` for current evals; `androidworld:2026plusswipe_tier4` for tier4 |
| `--port` | 9100 | HTTP port for `/acquire` etc. (the README uses 9300/9400) |
| `--base-env-id` | 0 | First env_id; bump if other brokers already use 0..N |
| `--parallel` | 4 | Max concurrent container creations |
| `--snapshot` | `clean` | Emulator snapshot name to restore on `/reset` |
| `--health-interval` | 30.0 | Health-check period (seconds) |
| `--gc-interval` | 60.0 | GC period — reclaims leases whose owner pid died |
| `--reconcile-interval` | 180.0 | Pool size reconciliation |
| `--adopt` | off | Adopt already-running containers instead of creating new ones |

### 3.2 Start the MobileWorld broker (no creation, just adoption)

```bash
PYTHONPATH=eval-runners/common/runtime:. \
python eval-runners/common/runtime/mw_pool_broker.py \
    --scan-range 6804-6819 --port 9400
```

`--scan-range` discovers any container exposing the MobileWorld API in the
given port range; `--containers` lets you pin specific URLs.

### 3.3 Run an experiment against the broker

The broker is benchmark-agnostic, so any of the runners under
`eval-runners/benchmarks/*/run_*.py` work the same way:

```bash
# AndroidWorld + Claude Code CLI
python eval-runners/benchmarks/androidworld/run_claude_cli.py \
    --data data/androidworld_original/val_data_seed7.jsonl \
    --broker-url http://localhost:9400 \
    --pool-size 16 \
    --model claude-opus-4-7 --max-turns 50

# AndroidWorld + Terminus2
python eval-runners/benchmarks/androidworld/run_terminus2.py \
    --data data/androidworld_original/val_data_seed7.jsonl \
    --broker-url http://localhost:9400 --pool-size 16 \
    --model openrouter/minimax/minimax-m2.7 --max-turns 50

# MobileWorld + GUI agent (Qwen3-VL)
python eval-runners/benchmarks/mobileworld/run_gui_agent_broker.py \
    --data eval-runners/data/mobileworld/gui_only_tasks.jsonl \
    --agent-type qwen3vl --broker-url http://localhost:9400 \
    --pool-size 16 --max-steps 50
```

### 3.4 Run training against the broker

In the verl YAML:

```yaml
env:
  broker_url: "http://localhost:9400"
  pool_size: 16
  docker_image: androidworld:2026plusswipe   # ignored in Mode B but kept for record
```

Training entry point: `skyrl-agent/examples/run_verl/verl_android_inference_broker.yaml`.
On first call, `AndroidTask.initialize_runtime()` instantiates a `PoolClient`
and a `BrokerContainerManager` and skips local container creation entirely.

> **Known issue (post-refactor):** `skyrl-agent/skyrl_agent/tasks/android/android_task.py`
> still imports `from skyrl_agent.runtime.android.pool_client import PoolClient,
> BrokerContainerManager`. Those modules now live under
> `eval-runners/common/runtime/`, so Mode B from training requires either
> patching that import or keeping `eval-runners/common/runtime` on `PYTHONPATH`.
> Track a fix when revisiting Mode B for training.

---

## 4. Quick start (Mode A — local)

Skip the broker; pass `pool_size`, `docker_image`, etc. directly in the YAML
and omit `broker_url`. `AndroidTask.initialize_runtime()` will:

1. Build a `ContainerManager` (`eval-runners/common/runtime/container_manager.py`).
2. Call `create_pool_parallel(pool_size, base_env_id, max_concurrent, ...)`.
3. Start a background `HealthMonitor`.
4. Hand `RuntimeClient`s to the dispatcher.

This is fine for one-off runs but spends ~5 min per experiment on container
boot.

---

## 5. Health, GC, reconcile loops

`ContainerPoolBroker` runs three asyncio tasks:

| Loop | Period | Job |
|---|---|---|
| Health | `--health-interval` | Probe every container's `/health`; mark unhealthy and queue replacement |
| GC | `--gc-interval` | Detect leases whose pid is dead (`psutil.pid_exists` + create-time check) and reclaim them |
| Reconcile | `--reconcile-interval` | Recreate destroyed/replaced containers up to `--pool-size` |

A `/return` with `healthy=false` triggers immediate replacement. A `/return`
with `healthy=true` triggers `/reset` on the container before re-listing it as
`IDLE`; that `/reset` is what restores the snapshot for the next acquirer.

---

## 6. Choosing pool ports

Convention used in the eval-runners README:

| Benchmark | Default broker port | Default container image |
|---|---|---|
| AndroidWorld | 9300 | `androidworld:2026` |
| MobileWorld | 9400 | `mobile_world:reset` |
| Tier4 | 9400 (often co-hosted) | `androidworld:2026plusswipe_tier4` |

Pick a free port whenever you spin up a parallel broker; `--base-env-id` keeps
container env IDs from colliding across brokers.

---

## 7. Debugging

| Symptom | Where to look |
|---|---|
| Broker stuck `pool_initializing=true` | Broker log — usually KVM contention; lower `--parallel` |
| Only env0 healthy | See [`../host_network_debugging.md`](../host_network_debugging.md) |
| `Broker unavailable at http://...` from runner | `curl <url>/health`; if 503, broker is up but pool not ready |
| Container leak after experiment crash | GC loop reclaims after one cycle; otherwise `docker ps --filter ancestor=androidworld:full_adb_agent` and clean up |
| `/return` 500 with snapshot restore error | Snapshot name mismatch between `--snapshot` and the image's saved snapshots |

For deeper failure modes consult [`../error_recovery.md`](../error_recovery.md)
(four-layer error model) and the integration tests under
`skyrl-agent/tests/integration/runtime/androidworld/`.

---

## 8. Code map

| File | Role |
|---|---|
| `eval-runners/common/runtime/pool_broker.py` | AndroidWorld broker (FastAPI, creates containers) |
| `eval-runners/common/runtime/mw_pool_broker.py` | MobileWorld broker (adopts containers) |
| `eval-runners/common/runtime/androidlab_broker.py` | AndroidLab broker |
| `eval-runners/common/runtime/pool_client.py` | `PoolClient` + `BrokerContainerManager` (used by Mode B clients) |
| `eval-runners/common/runtime/container_manager.py` | `ContainerManager`, `ContainerFactory`, `PortAllocator`, `HealthMonitor` (Mode A) |
| `eval-runners/common/runtime/runtime_client.py` | Async HTTP client for `/reset`, `/step`, `/step_adb` |
| `eval-runners/common/runtime/runtime_client_adb.py` | ADB-only fast-path client |
| `eval-runners/common/runtime/exceptions.py` | `ContainerDeadError`, etc. |
| `skyrl-agent/skyrl_agent/tasks/android/android_task.py` | Selects Mode A vs Mode B, owns lifecycle |
| `skyrl-agent/skyrl_agent/dispatcher/dispatchers.py` | `async_fix_pool_android` dispatcher; calls the manager interface |
