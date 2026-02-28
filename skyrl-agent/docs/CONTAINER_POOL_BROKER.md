# Container Pool Broker

This document describes the two modes for managing Android emulator containers in SkyRL-AndroidWorld and how to configure each.

## Overview

Each evaluation or training run needs a pool of Docker containers running Android emulators. There are two ways to manage them:

- **Mode A (Local)** — `ContainerManager` creates and destroys containers within the experiment process. Simple, self-contained, but slow to start and limited to one experiment at a time.
- **Mode B (Broker)** — `pool_broker.py` runs as a persistent HTTP server that owns a shared container pool. Experiments acquire and return containers on demand. Faster startup, shared across runs, survives experiment restarts.

## Architecture

```
MODE A — Local Container Management
====================================

  ┌──────────────────────────────────────────────┐
  │  Experiment Process                          │
  │                                              │
  │  AndroidTask.initialize_runtime()            │
  │       │                                      │
  │       ▼                                      │
  │  ContainerManager                            │
  │   ├── create_pool_parallel()  (slow: ~5 min) │
  │   ├── HealthMonitor (background)             │
  │   ├── allocate_container()                   │
  │   └── release_container()                    │
  │       │                                      │
  │       ▼                                      │
  │  Docker containers (created + destroyed      │
  │  with each experiment)                       │
  └──────────────────────────────────────────────┘


MODE B — Broker-Managed Container Pool
========================================

  ┌──────────────────┐    HTTP     ┌──────────────────────────┐
  │ Experiment 1     │◄──────────►│  pool_broker.py          │
  │  BrokerContainer │            │                          │
  │  Manager         │            │  ContainerPoolBroker     │
  └──────────────────┘            │   ├── health loop        │
                                  │   ├── GC loop            │
  ┌──────────────────┐            │   ├── reconcile loop     │
  │ Experiment 2     │◄──────────►│   └── container pool     │
  │  BrokerContainer │            │       ├── container 0    │
  │  Manager         │            │       ├── container 1    │
  └──────────────────┘            │       ├── ...            │
                                  │       └── container N    │
  ┌──────────────────┐            │                          │
  │ Experiment N     │◄──────────►│  Containers persist      │
  │  ...             │            │  across experiments      │
  └──────────────────┘            └──────────────────────────┘
```

## Quick Start (Mode B)

**1. Start the broker** (in a tmux/screen session):

```bash
cd skyrl-agent
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 \
  --port 9200 \
  --docker-image androidworld:full_adb_agent \
  --parallel 4
```

Wait for the log line indicating all containers are ready.

**2. Run inference** using the broker config:

```bash
# In your launch script, point to the broker yaml:
python skyrl_agent/integrations/verl/verl_main_inference.py \
  --config examples/run_verl/verl_android_inference_broker.yaml \
  ...
```

The key difference in the yaml is the `broker_url` field under `env:`:

```yaml
env:
  broker_url: "http://localhost:9200"
  pool_size: 16
  # ... other fields (managed by broker, kept for reference)
```

**3. Check pool status** anytime:

```bash
curl http://localhost:9200/status | python -m json.tool
```

**4. Stop the broker** when done (Ctrl-C or kill the process). Containers are cleaned up on shutdown.

## Mode A — Local Container Management

### How It Works

When `broker_url` is **absent** from the yaml `env:` section, `AndroidTask.initialize_runtime()` creates a `ContainerManager` that:

1. Pre-allocates ports atomically (avoids conflicts with other processes)
2. Creates `pool_size` containers in parallel (bounded by `max_concurrent=4`)
3. Optionally creates `buffer_size` hot-standby containers for instant failover
4. Starts a background `HealthMonitor` that checks containers every 30s
5. On experiment end, destroys all containers

### YAML Config

Use `verl_android_inference.yaml` (inference) or `verl_android.yaml` (training):

```yaml
env:
  pool_size: 16          # Number of containers
  buffer_size: 2         # Hot standby containers (0 for training)
  docker_image: androidworld:full_adb_agent
  use_host_network: true
  snapshot: clean
  sample_mode: sequential
  train_task_family: android_world
  val_task_family: android_world
  temp_path: /tmp/androidworld
  base_env_id: 0
```

### When to Use

- Single-user, single-experiment setups
- When you don't want a long-running broker process
- CI/test environments where containers should be cleaned up automatically

## Mode B — Broker-Managed Container Pool

### How It Works

When `broker_url` is **present** in the yaml `env:` section, `AndroidTask.initialize_runtime()` creates a `BrokerContainerManager` backed by a `PoolClient` that:

1. Connects to the broker and verifies it is healthy
2. Queries the broker's pool size via `GET /status`
3. Uses the experiment's `pool_size` yaml field (or the broker's total) for local scheduling
4. Acquires containers on demand via `POST /acquire` (per task)
5. Returns containers via `POST /return` after each task
6. Does **not** create or destroy any containers — the broker handles that

The broker itself (`ContainerPoolBroker`) runs three background loops:

| Loop | Default Interval | Purpose |
|------|-----------------|---------|
| Health | 30s | Check idle containers, replace unhealthy ones |
| GC | 60s | Reclaim containers from dead/expired processes |
| Reconcile | 180s | Ensure pool is at target size, create replacements |

### Starting the Broker

```bash
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 \
  --port 9200 \
  --docker-image androidworld:full_adb_agent \
  --snapshot clean \
  --parallel 4
```

To adopt already-running containers (e.g., after a broker restart):

```bash
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 \
  --port 9200 \
  --adopt
```

### YAML Config

Use `verl_android_inference_broker.yaml`:

```yaml
env:
  broker_url: "http://localhost:9200"   # Activates Mode B
  pool_size: 16       # Containers to acquire (can be <= broker pool size)
  buffer_size: 2      # Ignored in Mode B (broker manages buffer)
  docker_image: androidworld:full_adb_agent
  use_host_network: true
  snapshot: clean
  # ...
```

The `pool_size` in the yaml controls how many containers the experiment will try to use concurrently. It can be less than or equal to the broker's `--pool-size`. The broker's pool is shared — multiple experiments can acquire from it.

### When to Use

- Iterating on experiments (skip 5+ min container startup each time)
- Running multiple experiments that share a container pool
- Long-running evaluation servers
- Training loops where containers should survive between epochs

## Comparison

| | Mode A (Local) | Mode B (Broker) |
|---|---|---|
| **Container lifecycle** | Created/destroyed per experiment | Persistent, shared across experiments |
| **Startup time** | ~5 min (pool creation) | ~1s (HTTP connect) |
| **Multi-experiment** | No (one experiment owns containers) | Yes (broker multiplexes) |
| **Health monitoring** | Local `HealthMonitor` | Broker background loops |
| **Failover** | Hot standby (`buffer_size`) | Broker auto-replaces unhealthy containers |
| **Leak protection** | N/A (containers destroyed on exit) | GC reclaims from dead PIDs / expired leases |
| **Config field** | No `broker_url` in yaml | `broker_url` in yaml |
| **Extra process** | None | Broker server (must be running) |
| **Container class** | `ContainerInstance` | `RemoteContainerInfo` (duck-typed) |

## Broker CLI Reference

```
python -m skyrl_agent.runtime.android.pool_broker [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--pool-size` | int | 24 | Number of containers in the pool |
| `--docker-image` | str | `androidworld:v8` | Docker image to use |
| `--port` | int | 9100 | HTTP port for the broker API |
| `--snapshot` | str | `clean` | Emulator snapshot name to load |
| `--sample-mode` | str | `sequential` | Task sampling mode |
| `--base-env-id` | int | 0 | Starting environment ID |
| `--host` | str | `0.0.0.0` | Host to bind to |
| `--temp-path` | str | `/tmp` | Path for temporary files |
| `--health-interval` | float | 30.0 | Seconds between health checks on idle containers |
| `--gc-interval` | float | 60.0 | Seconds between garbage collection sweeps |
| `--reconcile-interval` | float | 180.0 | Seconds between pool size reconciliation |
| `--skip-screenshot` | flag | false | Skip saving screenshots |
| `--parallel` | int | 4 | Max concurrent container creations |
| `--adopt` | flag | false | Adopt existing containers instead of creating new ones |

## Broker API Reference

All endpoints are served at `http://<host>:<port>`.

### POST /acquire

Acquire a container from the pool.

**Request:**
```json
{
  "pid": 12345,
  "timeout": 300.0
}
```

- `pid` (int, required) — PID of the requesting process (used for leak detection)
- `timeout` (float, default 300) — Max seconds to wait for an available container

**Response (200):**
```json
{
  "env_id": 3,
  "server_port": 5006,
  "emulator_port": 5580,
  "grpc_port": 8580,
  "host": "localhost",
  "container_id": "abc123..."
}
```

**Response (503):** No container available within the timeout.

### POST /return

Return a container to the pool.

**Request:**
```json
{
  "env_id": 3,
  "healthy": true
}
```

- `env_id` (int, required) — The environment ID to return
- `healthy` (bool, default true) — If `false`, the broker replaces the container

**Response (200):**
```json
{"status": "returned"}
```

### GET /status

Get current pool status.

**Response (200):**
```json
{
  "total": 16,
  "idle": 12,
  "leased": 4,
  "replacing": 0,
  "containers": [
    {
      "env_id": 0,
      "state": "IDLE",
      "pid": null,
      "server_port": 5000,
      "healthy": true
    }
  ]
}
```

### GET /health

Broker health check.

**Response (200):**
```json
{
  "status": "ok",
  "uptime": 3600.5,
  "pool_size": 16
}
```

## Troubleshooting

### Broker won't start — port conflict

```
ERROR: Address already in use (0.0.0.0:9100)
```

Another broker or process is using the port. Either stop it or use a different `--port`.

### Experiment hangs on acquire (503 timeout)

All containers are leased. Check `GET /status` — if `leased` equals `total`, either:
- Another experiment is holding containers. Wait or stop it.
- Increase `--pool-size` and restart the broker.
- Containers are stuck in `REPLACING`. Wait for the reconcile loop to create replacements.

### Containers leak after experiment crash

The broker's GC loop detects dead PIDs and reclaims their containers every `--gc-interval` seconds (default 60s). No action needed — check `GET /status` to confirm containers return to `IDLE`.

The max lease duration is 600 seconds. Containers leased longer than that are reclaimed automatically.

### Broker restart without destroying containers

Use `--adopt` to take over existing containers:

```bash
python -m skyrl_agent.runtime.android.pool_broker --adopt --pool-size 16 --port 9200
```

The broker will discover running containers matching the expected env_id range and add them to the pool.

### Health check failures

If containers repeatedly fail health checks and get replaced, check:
- Docker daemon health: `docker ps`
- Emulator status inside the container: `docker logs <container_id>`
- Network connectivity: containers use host networking, so port conflicts can cause issues
- Disk space: emulator snapshots require significant disk I/O

### Mode selection not working

Mode selection happens in `AndroidTask.initialize_runtime()` (`skyrl_agent/tasks/android/android_task.py`). The logic is:

```python
if env_config.get("broker_url"):
    # Mode B: BrokerContainerManager
else:
    # Mode A: ContainerManager
```

If broker mode isn't activating, verify `broker_url` is set under the `env:` key in your yaml (not at the top level).

## Source Files

| File | Description |
|------|-------------|
| `skyrl_agent/runtime/android/pool_broker.py` | Broker server (`ContainerPoolBroker` + FastAPI app) |
| `skyrl_agent/runtime/android/pool_client.py` | HTTP client (`PoolClient`) and adapter (`BrokerContainerManager`) |
| `skyrl_agent/runtime/android/container_manager.py` | Local manager (`ContainerManager`, `HealthMonitor`, `PortAllocator`) |
| `skyrl_agent/tasks/android/android_task.py` | Mode selection logic in `initialize_runtime()` |
| `examples/run_verl/verl_android_inference_broker.yaml` | Inference config with broker (Mode B) |
| `examples/run_verl/verl_android_inference.yaml` | Inference config without broker (Mode A) |
| `examples/run_verl/verl_android.yaml` | Training config (Mode A) |
