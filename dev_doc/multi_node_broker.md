# Design Doc: Multi-Node Container Pool Broker

**Status:** Proposal
**Author:** —
**Date:** 2026-02-28

## 1. Problem

The current broker (`pool_broker.py`) runs on a single node. All containers live on the same machine as the broker, and the acquire response hardcodes `"host": "localhost"`. This limits scale to however many Android emulator containers one machine can support (~16-24 on an 8-GPU node).

### Target topology: separate GPU and CPU nodes

GPU nodes (Node A, Node B) are expensive and should be dedicated to inference (vLLM + FSDP). Android emulator containers are CPU-bound and should run on cheaper, dedicated CPU nodes. The plan is to rent additional CPU-only nodes as container hosts while GPU nodes run only the inference workload.

```
GPU Nodes (fixed, expensive)              CPU Nodes (elastic, cheap)
┌──────────────────┐                      ┌─────────────────────┐
│ GPU-A            │                      │ CPU-1               │
│  vLLM + FSDP     │── acquire/return ──►│  broker-1 :9200      │
│  inference only  │                      │  containers 0..15   │
└──────────────────┘                      └─────────────────────┘
┌──────────────────┐                      ┌─────────────────────┐
│ GPU-B            │                      │ CPU-2               │
│  vLLM + FSDP     │── acquire/return ──►│  broker-2 :9200      │
│  inference only  │                      │  containers 16..31  │
└──────────────────┘                      └─────────────────────┘
                                          ┌─────────────────────┐
                                          │ CPU-3               │
                                          │  broker-3 :9200      │
                                          │  containers 32..47  │
                                          └─────────────────────┘
                                               ... (add more)
```

We want to support:

1. **Remote broker** — inference on GPU nodes, broker + containers on CPU nodes.
2. **Multi-node pool** — containers spread across multiple CPU nodes, inference accesses all of them.
3. **Elastic scaling** — rent more CPU nodes, start a broker, add the URL to config. No changes to running infrastructure.

## 2. Options Considered

### Option 1: One Broker Per CPU Node + Client-Side Fan-Out

```
                         ┌───────────────────────────┐
                         │       CPU Node 1            │
                         │  broker-1 :9200              │
                         │  ├── container 0..15         │
                         │  └── health/GC/reconcile     │
                         └─────────▲───────────────────-┘
                                   │ HTTP
┌──────────────┐          acquire/return
│  Inference    │──────────────────┤
│  (GPU node)   │                  │ HTTP
└──────────────┘          acquire/return
                                   │
                         ┌─────────▼───────────────────-┐
                         │       CPU Node 2              │
                         │  broker-2 :9200                │
                         │  ├── container 16..31          │
                         │  └── health/GC/reconcile       │
                         └──────────────────────────────-─┘
```

Each CPU node runs its own broker managing only local containers. The inference client on GPU nodes knows about all brokers and distributes acquire calls across them.

**Pros:**
- Docker API calls stay local on each CPU node (fast, reliable)
- Health checks via `docker exec` are local — no false positives from network timeouts
- Fault isolation: one CPU node crash only affects its containers
- No need to expose Docker TCP socket
- Each broker is identical to today's single-node broker — minimal code change
- Elastic: rent a CPU node, start a broker, add URL to config — done
- GPU nodes stay clean — no Docker, no container management overhead
- CPU nodes are disposable — kill broker, return the rental, no coordination needed

**Cons:**
- Client must know all broker endpoints
- Client must handle per-broker failures and load balancing
- Pool-wide status requires querying all brokers

### Option 2: Single Broker with Remote Docker Daemons

```
┌──────────────────────────────────────┐
│          GPU Node A (or dedicated)    │
│  broker :9200                         │
│  ├── docker_client_1 (tcp://C1:2375)  │
│  │   └── container 0..15              │
│  ├── docker_client_2 (tcp://C2:2375)  │
│  │   └── container 16..31             │
│  └── health/GC/reconcile              │
└──────────────────────────────────────┘
            │               │
      Docker TCP API   Docker TCP API
            │               │
┌───────────┴──┐   ┌────────┴─────┐
│   CPU Node 1  │   │   CPU Node 2  │
│   dockerd     │   │   dockerd     │
│   :2375       │   │   :2375       │
└──────────────┘   └──────────────┘
```

A single broker manages containers across multiple CPU nodes by connecting to remote Docker daemons over TCP.

**Pros:**
- Single broker — simple client config (one URL)
- Centralized pool status and scheduling

**Cons:**
- Docker API calls over network (10-100ms each vs <1ms local)
- Must expose Docker TCP socket on every CPU node — security risk (root-equivalent access)
- Health checks via remote `docker exec` are unreliable (timeouts → false positives)
- Single point of failure: broker crash loses all containers on all nodes
- Scalability bottleneck: one process managing 100+ remote containers across many nodes
- Adding a CPU node requires restarting the broker (to add a new Docker client)
- Broker runs on a GPU node, wasting GPU resources on container management

## 3. Recommendation: Option 1

Option 1 is recommended for the GPU/CPU split topology. The key arguments:

1. **Docker operations are local by design.** `docker exec`, `docker inspect`, and health checks are designed for local use. Making them remote introduces latency, unreliability, and security exposure.

2. **GPU nodes stay clean.** No Docker daemon, no container management overhead on GPU nodes. They run only inference (vLLM + FSDP).

3. **CPU nodes are elastic and disposable.** Rent a CPU node → install Docker + start broker → add URL to yaml. Tear down by killing the broker and returning the rental. No coordination, no central broker restart needed.

4. **Fault isolation scales linearly.** Losing one CPU node loses only its containers. With Option 2, losing the single broker loses everything.

5. **No security exposure.** Option 2 requires exposing Docker TCP sockets on every CPU node — a root-equivalent attack surface.

| Concern | Option 1 (broker per CPU node) | Option 2 (single broker, remote Docker) |
|---|---|---|
| Network latency | Health checks local (<1ms) | Docker API over network (10-100ms) |
| Fault isolation | One CPU node down = its containers only | Broker down = all containers on all nodes |
| Security | No Docker TCP exposure | Must expose :2375 on every CPU node |
| Adding a node | Start broker, add URL | Restart broker with new Docker client |
| Removing a node | Kill broker, remove URL | Restart broker |
| GPU node overhead | None (only lightweight HTTP client) | Broker process + Docker clients |
| Scalability ceiling | Linear (each broker manages ~16-24) | Single broker bottleneck at 100+ |

The remainder of this doc designs Option 1 in detail.

## 4. Detailed Design

### 4.1 Broker Changes: Return Real Hostname

Today the broker hardcodes `"host": "localhost"` in the acquire response:

```python
# pool_broker.py:337-344 (current)
return {
    "env_id": env_id,
    "server_port": entry.container.server_port,
    "emulator_port": entry.container.emulator_port,
    "grpc_port": entry.container.grpc_port,
    "host": "localhost",                    # <-- problem
    "container_id": entry.container.container_id,
}
```

Change: add a `--hostname` CLI flag (defaults to `socket.gethostname()` or `socket.getfqdn()`). The acquire response returns this value:

```python
# proposed
return {
    ...
    "host": self.advertised_host,           # e.g. "node-b.internal" or "10.0.1.5"
}
```

The client (`PoolClient`) already stores and uses whatever `host` the broker returns — `RemoteContainerInfo.host` is used by `RuntimeClient` to connect. No client-side change needed for this part.

### 4.2 Client Changes: Multi-Broker Support

Add a `MultiBrokerClient` that wraps multiple `PoolClient` instances and distributes acquire/return calls.

```
MultiBrokerClient
├── PoolClient("http://node-a:9200")  ──►  broker-A
├── PoolClient("http://node-b:9200")  ──►  broker-B
└── (extensible to N brokers)
```

#### 4.2.1 YAML Config

```yaml
env:
  # Single broker (backward compatible):
  broker_url: "http://node-a:9200"

  # Multi-broker:
  broker_urls:
    - "http://node-a:9200"
    - "http://node-b:9200"

  pool_size: 32  # total across all brokers
```

Mode selection in `AndroidTask.initialize_runtime()`:

```python
if env_config.get("broker_urls"):
    # Multi-broker mode
    clients = [PoolClient(url) for url in env_config["broker_urls"]]
    multi_client = MultiBrokerClient(clients)
    manager = BrokerContainerManager(multi_client, pool_size)
elif env_config.get("broker_url"):
    # Single broker mode (unchanged)
    client = PoolClient(env_config["broker_url"])
    manager = BrokerContainerManager(client, pool_size)
else:
    # Mode A: local containers
    ...
```

#### 4.2.2 Acquire Strategy

`MultiBrokerClient.acquire()` should distribute requests across brokers. Two strategies are proposed, starting simple and upgrading as needed.

**Strategy A: Round-robin with failover** (start here)

```python
class MultiBrokerClient:
    def __init__(self, clients: List[PoolClient]):
        self.clients = clients
        self._index = 0  # round-robin counter
        self._ownership: Dict[int, PoolClient] = {}

    async def acquire(self, timeout: float = 300.0) -> RemoteContainerInfo:
        """Try brokers in round-robin order, skip unavailable ones."""
        errors = []
        for _ in range(len(self.clients)):
            client = self.clients[self._index % len(self.clients)]
            self._index += 1
            try:
                return await client.acquire(timeout=min(timeout, 30.0))
            except Exception as e:
                errors.append((client.broker_url, e))
                continue
        raise RuntimeError(
            f"All brokers exhausted: {errors}"
        )
```

Short per-broker timeout (30s) with fast failover. Simple and adequate when all CPU nodes have the same capacity.

**Strategy B: Capacity-aware routing** (upgrade when nodes differ)

When CPU nodes have different core counts or memory, prefer brokers with available containers instead of blind round-robin:

```python
async def acquire(self, timeout: float = 300.0) -> RemoteContainerInfo:
    """Try brokers with most idle containers first."""
    statuses = await asyncio.gather(
        *[c.get_status() for c in self.clients],
        return_exceptions=True,
    )
    # Rank by idle count, skip unreachable brokers
    ranked = sorted(
        [
            (c, s) for c, s in zip(self.clients, statuses)
            if isinstance(s, dict) and s.get("idle", 0) > 0
        ],
        key=lambda x: x[1]["idle"],
        reverse=True,
    )
    for client, _ in ranked:
        try:
            return await client.acquire(timeout=min(timeout, 30.0))
        except Exception:
            continue
    raise RuntimeError("All brokers exhausted or have no idle containers")
```

This avoids wasting a round-trip on a fully-leased broker. The status queries are parallel and fast (~1ms each).

#### 4.2.3 Return Strategy

Return is straightforward — route to the broker that owns the container. Track ownership at acquire time:

```python
async def acquire(...):
    info = await client.acquire(...)
    self._ownership[info.env_id] = client  # remember which broker owns it
    return info

async def release(env_id: int, healthy: bool = True):
    client = self._ownership.pop(env_id)
    await client.release(env_id, healthy)
```

#### 4.2.4 Status

Aggregate status from all brokers:

```python
async def get_status(self) -> Dict:
    statuses = await asyncio.gather(
        *[c.get_status() for c in self.clients],
        return_exceptions=True,
    )
    return {
        "total": sum(s["total"] for s in statuses if isinstance(s, dict)),
        "idle": sum(s["idle"] for s in statuses if isinstance(s, dict)),
        "leased": sum(s["leased"] for s in statuses if isinstance(s, dict)),
        "brokers": [
            {"url": c.broker_url, "status": s}
            for c, s in zip(self.clients, statuses)
        ],
    }
```

### 4.3 Network Requirements

Since containers use host network mode, their ports are bound to `0.0.0.0` on the CPU host machine. For cross-node access from GPU nodes:

| Port Type | Range | Direction | Notes |
|-----------|-------|-----------|-------|
| Broker API | 9200 (configurable) | GPU node → CPU node | HTTP acquire/return |
| Container HTTP (server_port) | 5000 + 2*env_id | GPU node → CPU node | Used by RuntimeClient for actions |
| ADB port | 5037 + env_id | Usually local only | Only if ADB needed cross-node |
| Emulator console | 5574 + 2*env_id | Local only | Not needed cross-node |
| gRPC port | emulator_port + 3000 | GPU node → CPU node | If gRPC used |

Firewall rules on CPU nodes must allow inbound connections from GPU nodes on:
- Broker port (9200)
- Server port range (5000-5063 for 32 containers)

### 4.4 Env ID Coordination

Each broker uses `--base-env-id` to claim a non-overlapping env_id range. Since each broker runs on its own CPU node, the env_ids only need to be unique for the `MultiBrokerClient`'s ownership tracking — there are no port collisions across different machines. However, non-overlapping env_ids make debugging and logging clearer:

```bash
# CPU-1: env_ids 0-15
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 --base-env-id 0 --port 9200 --hostname cpu-1

# CPU-2: env_ids 16-31
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 --base-env-id 16 --port 9200 --hostname cpu-2

# CPU-3: env_ids 32-47
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 --base-env-id 32 --port 9200 --hostname cpu-3
```

Convention: `base_env_id = node_index * pool_size`. Each broker can use the same `--port` since they are on different machines.

### 4.5 Failure Handling

| Scenario | Behavior |
|----------|----------|
| CPU node goes down | `MultiBrokerClient` skips it on acquire. Already-leased containers on that node time out; dispatcher retries on remaining brokers. Pool degrades but continues. |
| GPU ↔ CPU network partition | Acquire fails fast (connection refused/timeout), client tries next broker. |
| GPU ↔ container network issue | RuntimeClient HTTP calls fail. Container returned as unhealthy. Broker on the CPU node replaces it locally. |
| CPU node broker restarts | Use `--adopt` to reclaim running containers. Inference reconnects on next acquire. |
| Adding a CPU node | Start broker, add URL to yaml, restart inference. Running brokers are unaffected. |
| Removing a CPU node | Wait for leased containers to be returned (or let them time out), kill broker, remove URL from yaml. |

### 4.6 Deployment Example

```
GPU nodes:  gpu-a (10.0.1.10), gpu-b (10.0.1.11)  — inference only
CPU nodes:  cpu-1 (10.0.2.10), cpu-2 (10.0.2.11)  — containers only
```

**Step 1 — Start brokers on CPU nodes:**

```bash
# On cpu-1:
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 --base-env-id 0 --port 9200 \
  --hostname 10.0.2.10 --docker-image androidworld:full_adb_agent

# On cpu-2:
python -m skyrl_agent.runtime.android.pool_broker \
  --pool-size 16 --base-env-id 16 --port 9200 \
  --hostname 10.0.2.11 --docker-image androidworld:full_adb_agent
```

**Step 2 — Verify (from any node):**

```bash
curl http://10.0.2.10:9200/status | jq '.total, .idle'
curl http://10.0.2.11:9200/status | jq '.total, .idle'
```

**Step 3 — Inference config on GPU nodes:**

```yaml
env:
  broker_urls:
    - "http://10.0.2.10:9200"
    - "http://10.0.2.11:9200"
  pool_size: 32
  # ...
```

**Step 4 — Run inference on GPU nodes as usual.** `MultiBrokerClient` handles the rest.

**Step 5 — Scale up (later):** Rent cpu-3, start a broker with `--base-env-id 32`, add its URL, increase `pool_size` to 48.

## 5. Scaling Path

| Phase | Infra | Containers | Config Change |
|-------|-------|------------|---------------|
| **Current** | 2 GPU nodes, containers on same nodes | ~16-24 | Single `broker_url` |
| **Phase 1** | 2 GPU nodes + 1 CPU node | Move containers off GPU nodes → 16 on CPU-1 | Change `broker_url` to CPU-1's IP |
| **Phase 2** | 2 GPU nodes + 2 CPU nodes | 32 total (16 per CPU) | Switch to `broker_urls` list |
| **Phase 3** | 2 GPU nodes + N CPU nodes | 16*N total | Add URLs, bump `pool_size` |

Phase 1 is the most impactful — it frees GPU memory currently consumed by Docker/emulator overhead. Each subsequent phase is just "rent node, start broker, add URL."

### CPU Node Requirements

Android emulators are CPU and memory intensive. Per container:
- ~2 CPU cores (emulator + system processes)
- ~2-3 GB RAM
- ~5 GB disk (Docker image + snapshot)

A 32-core, 128 GB CPU node can comfortably run ~16 containers. Adjust `--pool-size` per node based on its capacity.

## 6. Implementation Plan

| Step | Change | Files | Dependency |
|------|--------|-------|------------|
| 1 | Add `--hostname` flag to broker; use in acquire response | `pool_broker.py` | None |
| 2 | Add `MultiBrokerClient` class | `pool_client.py` | None |
| 3 | Support `broker_urls` (list) in mode selection | `android_task.py` | Steps 1, 2 |
| 4 | Add `broker_urls` to example yaml | `verl_android_inference_broker.yaml` | Step 3 |
| 5 | Test: single remote broker (inference on GPU, broker on CPU) | manual | Step 1 |
| 6 | Test: two brokers, round-robin acquire | manual | Steps 1-4 |

Steps 1 and 2 are independent and can be done in parallel. Step 1 alone enables the single remote broker scenario (Phase 1 above).

## 7. Future Considerations

- **Capacity-aware routing** — upgrade from round-robin to idle-count-based routing when CPU nodes have different capacities (see Strategy B in 4.2.2).
- **Broker discovery** — instead of hardcoding URLs in yaml, brokers could register with a lightweight service registry (e.g., a shared file, etcd, or DNS SRV records). Not needed below ~5 nodes; worthwhile at 10+.
- **Cross-node ADB** — current inference workflows only use the container HTTP API, not ADB. If training needs ADB across nodes, ADB ports must be forwarded or `adb connect <host>:<port>` used remotely.
- **Container migration** — not planned. If a CPU node goes down, its containers are lost. The remaining brokers continue serving with a degraded pool.
- **Auto-scaling** — integrate with cloud APIs (e.g., AWS EC2, GCP) to automatically provision CPU nodes when the pool is exhausted and tear them down when idle. Each provisioned node runs the standard broker startup script.
- **Hot-add brokers** — currently adding a broker URL requires restarting the inference process. A future improvement could let `MultiBrokerClient` accept new URLs at runtime (e.g., via a control endpoint or config file watch).
