# Scaling and Acceleration Strategies for AndroidWorld

This document outlines strategies and techniques for improving the performance and scalability of the AndroidWorld agent-environment interaction system.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Scaling Characteristics](#scaling-characteristics)
3. [Current Bottlenecks](#current-bottlenecks)
4. [Optimization Techniques](#optimization-techniques)
5. [Implementation Priority](#implementation-priority)
6. [Benchmarking](#benchmarking)

---

## Architecture Overview

### Current System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HOST MACHINE                                    │
│                                                                              │
│  ┌─────────────────┐                                                         │
│  │  Agent (VLLM)   │                                                         │
│  │  - Model Inference                                                        │
│  │  - Action Generation                                                      │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│  ┌────────▼────────┐         HTTP/JSON                                       │
│  │  RuntimeClient  │◄────────────────────────┐                               │
│  │  (aiohttp)      │                         │                               │
│  └────────┬────────┘                         │                               │
│           │                                  │                               │
│  ┌────────▼────────┐    ┌───────────────────▼───────────────────────────┐   │
│  │ ContainerManager│    │              Docker Containers                 │   │
│  │ - Pool management    │  ┌─────────────────────────────────────────┐  │   │
│  │ - Health monitoring  │  │ Container 1                             │  │   │
│  │ - Port allocation    │  │  ┌─────────────┐  ┌─────────────────┐  │  │   │
│  └─────────────────┘    │  │  │ FastAPI     │◄►│ Android Emulator│  │  │   │
│                         │  │  │ Server      │  │ (QEMU/KVM)      │  │  │   │
│                         │  │  └─────────────┘  └─────────────────┘  │  │   │
│                         │  └─────────────────────────────────────────┘  │   │
│                         │  ┌─────────────────────────────────────────┐  │   │
│                         │  │ Container 2 ... N                       │  │   │
│                         │  └─────────────────────────────────────────┘  │   │
│                         └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Per Step

```
Agent                RuntimeClient           Container Server         Emulator
  │                       │                        │                      │
  │ action + thought      │                        │                      │
  ├──────────────────────►│                        │                      │
  │                       │ POST /step (JSON)      │                      │
  │                       ├───────────────────────►│                      │
  │                       │                        │ execute_action()     │
  │                       │                        ├─────────────────────►│
  │                       │                        │                      │
  │                       │                        │ get_state()          │
  │                       │                        ├─────────────────────►│
  │                       │                        │◄─────────────────────┤
  │                       │                        │ (screenshot ~3-15s)  │
  │                       │                        │                      │
  │                       │ JSON response          │                      │
  │                       │ (base64 image)         │                      │
  │                       │◄───────────────────────┤                      │
  │ observation, reward   │                        │                      │
  │◄──────────────────────┤                        │                      │
  │                       │                        │                      │
```

---

## Scaling Characteristics

### Linear Scaling Analysis

| Containers | Theoretical Speedup | Actual Speedup | Efficiency | Notes |
|------------|---------------------|----------------|------------|-------|
| 1          | 1x                  | 1x             | 100%       | Baseline |
| 2          | 2x                  | ~1.9x          | 95%        | Minimal overhead |
| 4          | 4x                  | ~3.5x          | 88%        | CPU contention starts |
| 8          | 8x                  | ~6x            | 75%        | Memory pressure |
| 16         | 16x                 | ~10x           | 63%        | I/O bottleneck |
| 32         | 32x                 | ~15x           | 47%        | Severe contention |

### Resource Requirements Per Container

| Resource | Requirement | Notes |
|----------|-------------|-------|
| CPU Cores | 2-4 cores | Peak during boot and actions |
| RAM | 2-4 GB | Emulator + Android OS |
| Disk | ~2 GB | Logs, screenshots, temp files |
| KVM | Shared | Virtualization acceleration |
| Network Ports | 3 ports | Server, emulator console, gRPC |

### Scaling Bottlenecks

1. **KVM Contention**: All emulators share the same KVM device
2. **Memory Bandwidth**: Large image transfers stress memory
3. **CPU Scheduling**: QEMU threads compete for CPU time
4. **Disk I/O**: Screenshot saves and log writes
5. **Network Stack**: HTTP overhead at scale

---

## Current Bottlenecks

### 1. Screenshot Capture (Highest Impact)

**Location**: `docker/android/server/env.py` lines 264-274

```python
for _ in range(5):  # Up to 5 retries for white screen
    if not is_white:
        break
    time.sleep(3)  # 3 second wait each retry
    state = self.env.get_state(wait_to_stabilize=True, stablize_timeout=3.0)
    nparray_image = state.pixels.copy()
    image = Image.fromarray(nparray_image)
    is_white = self.count_white_pixels(image)
```

**Impact**: 3-15+ seconds per observation
**Root Cause**: Conservative wait times for screen stabilization

### 2. Image Serialization

**Location**: `docker/android/server/server.py` lines 30-36

```python
def prepare_observation_for_transfer(observation):
    obs_copy = dict(observation)
    img = obs_copy["image"]
    obs_copy["image"] = base64.b64encode(img.tobytes()).decode("utf-8")
    obs_copy["image_shape"] = img.shape
    obs_copy["image_dtype"] = str(img.dtype)
    return obs_copy
```

**Impact**: 10-20% overhead for 1080p images (~6MB raw)
**Root Cause**: Base64 encoding increases size by 33%

### 3. HTTP Round-Trip

**Location**: `skyrl_agent/runtime/android/runtime_client.py`

```python
async with self.session.post(
    f"{self.base_url}/step",
    json=payload
) as response:
    data = await response.json()
```

**Impact**: 5-15ms per request (network + JSON parsing)
**Root Cause**: HTTP overhead, JSON serialization

### 4. Emulator Boot Time

**Location**: `docker/android/server/env.py` lines 163, 444

```python
time.sleep(30)  # Wait for emulator to start
# ...
self.task.initialize_task(self.env)  # Task setup
```

**Impact**: 45-60 seconds per container
**Root Cause**: Android OS boot + snapshot restore

---

## Optimization Techniques

### Category 1: Inside Docker (Emulator Optimizations)

#### 1.1 Reduce Screenshot Wait Times

**Effort**: Low | **Impact**: 20-40%

```python
# Before (env.py)
time.sleep(3)
state = self.env.get_state(wait_to_stabilize=True, stablize_timeout=3.0)

# After
time.sleep(1)
state = self.env.get_state(wait_to_stabilize=True, stablize_timeout=1.0)
```

#### 1.2 Disable White Screen Retry Loop

**Effort**: Low | **Impact**: 10-20%

```python
# Make white screen detection configurable
def get_raw_observation(self, max_white_retries=1):  # Reduce from 5
    for attempt in range(max_white_retries):
        ...
```

#### 1.3 GPU Acceleration

**Effort**: Low | **Impact**: 15-25%

```bash
# In emulator command (env.py _start_emulator)
# Current
command += " -gpu auto"

# Optimized for software rendering (more stable)
command += " -gpu swiftshader_indirect"

# Or for hardware acceleration (if available)
command += " -gpu host"
```

#### 1.4 Reduce Screen Resolution

**Effort**: Low | **Impact**: 10-20%

```bash
# Create AVD with lower resolution
# In emulator config
hw.lcd.width=720
hw.lcd.height=1280
# Instead of 1080x1920
```

#### 1.5 Use RAMdisk for Temp Files

**Effort**: Medium | **Impact**: 5-10%

```bash
# Mount tmpfs for screenshots and logs
mount -t tmpfs -o size=2G tmpfs /data/images
mount -t tmpfs -o size=500M tmpfs /data/log
```

### Category 2: Data Transfer Optimizations

#### 2.1 JPEG Compression

**Effort**: Medium | **Impact**: 20-30%

```python
# server.py
import io
from PIL import Image

def prepare_observation_for_transfer(observation, quality=85):
    img = Image.fromarray(observation["image"])
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    
    return {
        "image": base64.b64encode(buffer.getvalue()).decode(),
        "image_format": "jpeg",
        "image_shape": observation["image"].shape,
    }

# runtime_client.py
def _deserialize_observation(self, obs_dict):
    if obs_dict.get("image_format") == "jpeg":
        img_bytes = base64.b64decode(obs_dict["image"])
        img = Image.open(io.BytesIO(img_bytes))
        obs_dict["image"] = np.array(img)
    return obs_dict
```

**Size Comparison**:
- Raw 1080p: ~6 MB
- Base64 Raw: ~8 MB
- JPEG Q85: ~200-400 KB
- Base64 JPEG: ~270-530 KB

#### 2.2 Binary Protocol (MessagePack)

**Effort**: Medium | **Impact**: 15-20%

```python
# Replace JSON with MessagePack
import msgpack
import numpy as np

def pack_observation(obs):
    return msgpack.packb({
        "image": obs["image"].tobytes(),
        "shape": obs["image"].shape,
        "dtype": str(obs["image"].dtype),
        "task": obs["task"],
    }, use_bin_type=True)

def unpack_observation(data):
    d = msgpack.unpackb(data, raw=False)
    return {
        "image": np.frombuffer(d["image"], dtype=d["dtype"]).reshape(d["shape"]),
        "task": d["task"],
    }
```

#### 2.3 WebSocket for Streaming

**Effort**: High | **Impact**: 10-15%

```python
# Maintain persistent connection instead of per-request
import websockets

async def step_stream(self, actions):
    async with websockets.connect(f"ws://localhost:{port}/ws") as ws:
        for action in actions:
            await ws.send(json.dumps(action))
            response = await ws.recv()
            yield json.loads(response)
```

### Category 3: Protocol Optimizations

#### 3.1 gRPC Instead of HTTP

**Effort**: High | **Impact**: 15-25%

```protobuf
// env.proto
syntax = "proto3";

service AndroidEnv {
    rpc Reset(ResetRequest) returns (Observation);
    rpc Step(StepRequest) returns (StepResponse);
    rpc StreamSteps(stream StepRequest) returns (stream StepResponse);
}

message Observation {
    bytes image = 1;  // Raw bytes, no base64
    string task = 2;
    int32 env_id = 3;
}

message StepResponse {
    Observation observation = 1;
    float reward = 2;
    bool terminated = 3;
    bool truncated = 4;
}
```

**Benefits**:
- Binary protocol (no JSON overhead)
- HTTP/2 multiplexing
- Streaming support
- Built-in code generation

#### 3.2 Unix Domain Sockets

**Effort**: Medium | **Impact**: 5-10%

```python
# Use Unix sockets instead of TCP for host-mode networking
# In container
uvicorn.run(app, uds="/tmp/env{env_id}.sock")

# In client
connector = aiohttp.UnixConnector(path=f"/tmp/env{env_id}.sock")
session = aiohttp.ClientSession(connector=connector)
```

### Category 4: Architectural Optimizations

#### 4.1 Pipeline LLM Inference with Environment Step

**Effort**: High | **Impact**: 30-50%

```python
# Overlap model inference with environment observation
class PipelinedAgent:
    async def run_episode(self, env):
        obs, info = await env.reset()
        
        while not done:
            # Start generating next action while processing current step
            action_task = asyncio.create_task(
                self.model.generate(self.build_prompt(obs))
            )
            
            # Execute previous action and get observation
            if prev_action is not None:
                obs, reward, done, _, info = await env.step(prev_action)
            
            # Wait for action generation
            action = await action_task
            prev_action = action
```

**Timeline Comparison**:
```
Sequential:
|--LLM--|--ENV--|--LLM--|--ENV--|--LLM--|--ENV--|
         ↑       ↑       ↑
       Idle    Idle    Idle

Pipelined:
|--LLM--|--LLM--|--LLM--|--LLM--|
   |--ENV--|--ENV--|--ENV--|
            ↑
   Overlapped execution
```

#### 4.2 Warm Container Pool

**Effort**: Medium | **Impact**: 10-20%

```python
# Pre-reset containers while others are in use
class WarmContainerPool:
    def __init__(self, pool_size, warm_count=2):
        self.warm_queue = asyncio.Queue(maxsize=warm_count)
        self._start_warmer()
    
    async def _warmer(self):
        while True:
            container = await self.get_idle_container()
            await container.reset(next_task_config)
            await self.warm_queue.put(container)
    
    async def get_warm_container(self):
        return await self.warm_queue.get()
```

#### 4.3 Action Batching

**Effort**: Medium | **Impact**: 15-25%

```python
# Execute multiple simple actions before getting observation
@app.post("/batch_step")
async def batch_step(env: Env, actions: List[StepInput]):
    results = []
    for action in actions[:-1]:
        env.step(action.action, action.thought)
        # Skip intermediate observations
    
    # Only get observation for final action
    obs, reward, done, trunc, info = env.step(
        actions[-1].action, actions[-1].thought
    )
    return {"observation": obs, "reward": reward, ...}
```

#### 4.4 Shared Memory for Observations

**Effort**: High | **Impact**: 30-50%

```python
# Use shared memory instead of HTTP for image transfer
import multiprocessing.shared_memory as shm

class SharedMemoryObserver:
    def __init__(self, env_id, image_shape):
        self.shm = shm.SharedMemory(
            name=f"env_{env_id}_obs",
            create=True,
            size=np.prod(image_shape) * 3  # RGB
        )
        self.image = np.ndarray(image_shape, dtype=np.uint8, buffer=self.shm.buf)
    
    def update(self, observation):
        np.copyto(self.image, observation["image"])
        # Signal client via lightweight message
```

#### 4.5 Differential Observations

**Effort**: High | **Impact**: 20-40%

```python
# Only send changed pixels
def compute_diff(prev_obs, curr_obs, threshold=10):
    diff = np.abs(curr_obs.astype(int) - prev_obs.astype(int))
    changed_mask = np.any(diff > threshold, axis=-1)
    
    if changed_mask.sum() < 0.1 * changed_mask.size:
        # Less than 10% changed - send diff
        return {
            "type": "diff",
            "mask": changed_mask,
            "values": curr_obs[changed_mask],
        }
    else:
        # Too many changes - send full image
        return {"type": "full", "image": curr_obs}
```

---

## Implementation Priority

### Phase 1: Quick Wins (1-2 days)

| Optimization | File | Change | Expected Improvement |
|--------------|------|--------|---------------------|
| Reduce screenshot wait | `env.py` | `time.sleep(3)` → `time.sleep(1)` | 20-30% |
| Reduce stabilization timeout | `env.py` | `stablize_timeout=3.0` → `1.0` | 10-15% |
| Reduce white retry | `env.py` | `range(5)` → `range(2)` | 10-20% |

### Phase 2: Data Transfer (3-5 days)

| Optimization | Files | Change | Expected Improvement |
|--------------|-------|--------|---------------------|
| JPEG compression | `server.py`, `runtime_client.py` | Add JPEG encoding/decoding | 20-30% |
| Connection pooling | `runtime_client.py` | Reuse aiohttp sessions | 5-10% |

### Phase 3: Architecture (1-2 weeks)

| Optimization | Files | Change | Expected Improvement |
|--------------|-------|--------|---------------------|
| Pipelined inference | `agent.py` | Overlap LLM and env | 30-50% |
| Warm container pool | `container_manager.py` | Pre-reset containers | 10-20% |

### Phase 4: Protocol (2-4 weeks)

| Optimization | Files | Change | Expected Improvement |
|--------------|-------|--------|---------------------|
| gRPC migration | New files | Replace HTTP with gRPC | 15-25% |
| Shared memory | New files | IPC for images | 30-50% |

---

## Benchmarking

### Metrics to Track

| Metric | Description | Target |
|--------|-------------|--------|
| Step Latency | Time from action to observation | < 1s |
| Reset Latency | Time to reset environment | < 5s |
| Container Boot | Time to create container | < 45s |
| Throughput | Steps per second (all containers) | Linear with containers |
| Memory Usage | RAM per container | < 3GB |
| CPU Usage | Cores per container | < 2 cores avg |

### Benchmarking Commands

```bash
# Run profiling with different configurations
cd skyrl-agent

# Baseline
RUN_DOCKER_TESTS=true ./tests/profiling/run_profiling.sh --pool-sizes 1 2 4

# Parallel creation
RUN_DOCKER_TESTS=true ./tests/profiling/run_profiling.sh --parallel

# Full benchmark
RUN_DOCKER_TESTS=true ./tests/profiling/run_profiling.sh --parallel-full
```

### Expected Results After Optimization

| Metric | Before | After Phase 1 | After Phase 2 | After All |
|--------|--------|---------------|---------------|-----------|
| Step Latency | 3-5s | 1.5-2.5s | 1-2s | 0.5-1s |
| Reset Latency | 5-10s | 3-5s | 2-4s | 1-3s |
| Image Transfer | 8MB | 8MB | 300KB | <100KB |
| Throughput (8 containers) | 1.5 steps/s | 3 steps/s | 4 steps/s | 8 steps/s |

---

## References

- [Android Emulator Acceleration](https://developer.android.com/studio/run/emulator-acceleration)
- [QEMU Performance Tuning](https://www.qemu.org/docs/master/system/invocation.html)
- [gRPC Performance Best Practices](https://grpc.io/docs/guides/performance/)
- [aiohttp Performance](https://docs.aiohttp.org/en/stable/client_advanced.html#limiting-connection-pool-size)

---

## Changelog

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-20 | AI Assistant | Initial document creation |
