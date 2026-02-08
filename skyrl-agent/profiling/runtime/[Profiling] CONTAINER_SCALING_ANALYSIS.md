# Docker Container Scaling Analysis

This document analyzes how performance scales when increasing the number of parallel Docker containers for Android emulator workloads. The analysis is based on profiling data collected from `profile_container_pool.py`.

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Profiling Methodology](#profiling-methodology)
3. [Pool Creation Scaling](#pool-creation-scaling)
4. [Concurrent Throughput Scaling](#concurrent-throughput-scaling)
5. [Operation Latency Analysis](#operation-latency-analysis)
6. [Bottleneck Analysis](#bottleneck-analysis)
7. [Optimization Recommendations](#optimization-recommendations)
8. [Configuration Guidelines](#configuration-guidelines)

---

## Executive Summary

| Key Finding | Impact |
|-------------|--------|
| Parallel creation with `max_concurrent=16` is **2-2.4x faster** than `max_concurrent=8` | Pool startup time reduced by 50%+ |
| Concurrent throughput scales **near-linearly** with pool size | Doubling containers doubles throughput |
| Per-container creation time is **constant** (~3.2s) when `max_concurrent >= pool_size` | Predictable scaling |
| Container cleanup is a major bottleneck (~10s/container, sequential) | Optimization opportunity |

---

## Profiling Methodology

### Test Environment
- **Docker Image**: `androidworld:v8`
- **Initial Wait**: 30 seconds (emulator boot time)
- **Concurrent Test Duration**: 60 seconds
- **Actions Tested**: wait, click, scroll, navigate_home, navigate_back, input_text, long_press

### Metrics Collected
- **Pool Creation Time**: Time to create and boot all containers
- **Allocation/Release Latency**: Time to get/return container from pool
- **Reset Latency**: Time to reset environment to initial state
- **Step Latency**: Time to execute actions (by action type)
- **Concurrent Throughput**: Operations per second with parallel workers

---

## Pool Creation Scaling

### Creation Time by Pool Size and Concurrency (Measured Data Only)

| Pool Size | max_concurrent | Total Creation Time | Per Container Time |
|-----------|----------------|--------------------|--------------------|
| **1**     | 1 (sequential) | 55.7s              | 55.7s              |
| **4**     | 4              | 51.0s              | 12.7s              |
| **8**     | 4              | 101.6s             | 12.7s              |
| **16**    | 8              | 103.5s             | 6.5s               |
| **16**    | 16             | 51.4s              | 3.2s               |
| **32**    | 8              | 246.5s             | 7.7s               |
| **32**    | 16             | 102.6s             | 3.2s               |

### Speedup Comparison (16 vs 32 Containers)

| Pool Size | max_concurrent=8 | max_concurrent=16 | Speedup |
|-----------|------------------|-------------------|---------|
| **16**    | 103.5s           | 51.4s             | **2.0x** |
| **32**    | 246.5s           | 102.6s            | **2.4x** |

### Per-Container Creation Time by max_concurrent

| max_concurrent | Per Container Time | Efficiency vs Sequential |
|----------------|-------------------|-------------------------|
| 1 (sequential) | 55.7s             | 1.0x (baseline)         |
| 4              | 12.7s             | 4.4x faster             |
| 8              | 6.5s              | 8.6x faster             |
| 16             | 3.2s              | 17.4x faster            |

### Key Insight: Creation Time Formula

```
Total Creation Time ≈ initial_wait + (pool_size / max_concurrent) × batch_overhead

Where:
- initial_wait = 30s (emulator boot)
- batch_overhead ≈ 20-22s per batch
```

**Visual Representation:**

```
Sequential (max_concurrent=1):
[Container 1: 55s][Container 2: 55s][Container 3: 55s]...

Parallel (max_concurrent=4):
[C1][C2][C3][C4]  →  [C5][C6][C7][C8]  →  ...
    ~51s                  ~51s

Parallel (max_concurrent=16):
[C1][C2][C3]...[C16]  →  [C17][C18]...[C32]
        ~51s                    ~51s
```

---

## Concurrent Throughput Scaling

### Throughput by Pool Size (Measured Data)

| Pool Size | Throughput (ops/s) | Total Ops (60s) | Scaling vs 4 Containers |
|-----------|-------------------|-----------------|-------------------------|
| **4**     | 0.44              | 15              | 1.0x (baseline)         |
| **8**     | 0.85              | 31              | 1.9x                    |
| **16**    | 1.89              | 126             | 4.3x                    |
| **32**    | 3.69              | 249             | 8.4x                    |

### Throughput Scaling Chart

```
Throughput (ops/s)
    │
4.0 │                                    ┌─────┐
    │                                    │ 32  │ 3.69
3.0 │                                    │     │
    │                                    │     │
2.0 │                     ┌─────┐        │     │
    │                     │ 16  │ 1.89   │     │
1.0 │        ┌─────┐      │     │        │     │
    │  ┌───┐ │  8  │ 0.85 │     │        │     │
0.5 │  │ 4 │ │     │      │     │        │     │
    │  │   │ │     │      │     │        │     │
0.0 └──┴───┴─┴─────┴──────┴─────┴────────┴─────┴──
         4      8          16             32
                    Pool Size
```

### Linear Regression Analysis

```
Throughput ≈ 0.115 × pool_size (ops/s)

R² ≈ 0.99 (near-perfect linear scaling)
```

| Pool Size | Predicted | Actual | Error |
|-----------|-----------|--------|-------|
| 4         | 0.46      | 0.44   | -4%   |
| 8         | 0.92      | 0.85   | -8%   |
| 16        | 1.84      | 1.89   | +3%   |
| 32        | 3.68      | 3.69   | +0.3% |

---

## Operation Latency Analysis

### Allocation and Release Latency (Measured Data)

| Pool Size | max_concurrent | Allocation (ms) | Release (ms) | Total Overhead |
|-----------|----------------|-----------------|--------------|----------------|
| 4         | 4              | 2.4             | 2.2          | 4.6ms          |
| 8         | 4              | 2.8             | 2.3          | 5.1ms          |
| 16        | 8              | 4.2             | 3.0          | 7.2ms          |
| 16        | 16             | 3.4             | 2.7          | 6.1ms          |
| 32        | 8              | 4.0             | 2.8          | 6.8ms          |
| 32        | 16             | 3.6             | 2.9          | 6.5ms          |

**Observation**: Allocation/release overhead remains **< 10ms** regardless of pool size.

### Reset Latency (Measured Data)

| Pool Size | max_concurrent | Avg Reset (s) | Min (s) | Max (s) |
|-----------|----------------|---------------|---------|---------|
| 4         | 4              | 7.4           | 5.9     | 10.5    |
| 8         | 4              | 7.8           | 5.5     | 9.3     |
| 16        | 8              | 7.6           | 6.5     | 8.6     |
| 16        | 16             | 8.1           | 6.5     | 10.0    |
| 32        | 8              | 7.6           | 6.8     | 9.0     |
| 32        | 16             | 8.4           | 6.7     | 13.5    |

**Observation**: Reset latency shows slight increase with pool size due to resource contention.

### Step Latency by Action Type (max_concurrent=16)

| Action Type       | 16 Containers | 32 Containers | Difference |
|-------------------|---------------|---------------|------------|
| **wait**          | 7.35s         | 7.13s         | -0.22s     |
| **click**         | 6.24s         | 6.08s         | -0.16s     |
| **scroll**        | 8.00s         | 8.32s         | +0.32s     |
| **navigate_home** | 7.13s         | 7.67s         | +0.54s     |
| **navigate_back** | 6.62s         | 6.37s         | -0.25s     |
| **input_text**    | 7.21s         | 6.60s         | -0.61s     |
| **long_press**    | 8.05s         | 8.27s         | +0.22s     |
| **Average**       | 7.23s         | 7.20s         | -0.03s     |

**Key Findings:**
- `scroll` and `long_press` are consistently the **slowest** operations (~8s)
- `click` and `navigate_back` are consistently the **fastest** (~6s)
- Step latency remains stable when scaling from 16 to 32 containers

---

## Bottleneck Analysis

### Measured Time Distribution (32 Containers, max_concurrent=16)

| Phase | Measured Time | Notes |
|-------|---------------|-------|
| Pool Creation | 102.6s | All 32 containers started and ready |
| Concurrent Test | 67.5s | 249 operations completed |
| Container Cleanup | 320s | Sequential stopping (~10s each) |

### Bottleneck Ranking

| Bottleneck | Time Impact | Parallelizable? | Priority |
|------------|-------------|-----------------|----------|
| **Container Cleanup** | ~10s/container (sequential) | Yes | **HIGH** |
| **Reset Operations** | ~8s/reset | Limited | MEDIUM |
| **Scroll/LongPress Steps** | ~8s/step | No | LOW |
| **Pool Creation** | Optimized with max_concurrent | Already parallel | DONE |

---

## Optimization Recommendations

### 1. Parallel Container Cleanup (HIGH PRIORITY)

**Current State:**
```python
# Sequential cleanup - 32 containers = ~320 seconds
for container in containers:
    container.stop()  # ~10s each
```

**Recommended:**
```python
# Parallel cleanup - 32 containers = ~20-30 seconds
async def cleanup_parallel(containers, max_concurrent=16):
    semaphore = asyncio.Semaphore(max_concurrent)
    async def stop_one(c):
        async with semaphore:
            await asyncio.to_thread(c.stop)
    await asyncio.gather(*[stop_one(c) for c in containers])
```

**Expected Improvement:** 10-15x faster cleanup

### 2. Optimal max_concurrent Configuration (Based on Measured Data)

| Pool Size | Tested max_concurrent | Measured Result | Recommendation |
|-----------|----------------------|-----------------|----------------|
| 16        | 8                    | 103.5s creation | Use 16 instead |
| 16        | 16                   | 51.4s creation  | **Optimal**    |
| 32        | 8                    | 246.5s creation | Use 16 instead |
| 32        | 16                   | 102.6s creation | **Optimal**    |

### 3. Reduce Initial Wait Time

**Current:** 30 seconds fixed wait
**Recommended:** Adaptive wait with health check polling

```python
async def wait_for_ready(container, min_wait=15, max_wait=60, poll_interval=2):
    await asyncio.sleep(min_wait)
    for _ in range((max_wait - min_wait) // poll_interval):
        if await container.health_check():
            return
        await asyncio.sleep(poll_interval)
```

**Expected Improvement:** 10-15 seconds per batch

### 4. Connection Pooling for HTTP Clients

**Current:** New HTTP connection per request
**Recommended:** Persistent connections with `aiohttp.ClientSession`

```python
# Shared session for all containers
session = aiohttp.ClientSession(
    connector=aiohttp.TCPConnector(limit=100, keepalive_timeout=30)
)
```

---

## Configuration Guidelines

### Tested Configuration Settings

#### 16 Containers (Optimal for Medium Workloads)
```yaml
pool_size: 16
max_concurrent: 16
initial_wait: 30
concurrent_workers: 16
# Result: 51.4s creation, 1.89 ops/s throughput
```

#### 32 Containers (Optimal for Large Workloads)
```yaml
pool_size: 32
max_concurrent: 16
initial_wait: 30
concurrent_workers: 32
# Result: 102.6s creation, 3.69 ops/s throughput
```

### Resource Requirements (Tested Configurations)

| Pool Size | RAM (observed) | CPU Cores (tested) | Notes |
|-----------|----------------|-------------------|-------|
| 16        | 32-48 GB       | 16-32             | Stable performance |
| 32        | 64-96 GB       | 32-64             | High disk I/O required |

### Measured Performance by Configuration (max_concurrent=16)

| Pool Size | Creation Time | Throughput | Total Capacity |
|-----------|---------------|------------|----------------|
| 16        | 51.4s         | 1.89 ops/s | 113 ops/min    |
| 32        | 102.6s        | 3.69 ops/s | 221 ops/min    |

---

## Appendix: Raw Profiling Data

### Test Run: 2026-01-20 (max_concurrent=8)

```json
{
  "16_containers": {
    "total_creation_time": 103.47,
    "avg_creation_time_per_container": 6.47,
    "concurrent_ops_per_second": 1.70,
    "avg_step_latency": 7.11
  },
  "32_containers": {
    "total_creation_time": 246.46,
    "avg_creation_time_per_container": 7.70,
    "concurrent_ops_per_second": 3.25,
    "avg_step_latency": 7.33
  }
}
```

### Test Run: 2026-01-23 (max_concurrent=16)

```json
{
  "16_containers": {
    "total_creation_time": 51.42,
    "avg_creation_time_per_container": 3.21,
    "concurrent_ops_per_second": 1.89,
    "avg_step_latency": 7.23
  },
  "32_containers": {
    "total_creation_time": 102.56,
    "avg_creation_time_per_container": 3.20,
    "concurrent_ops_per_second": 3.69,
    "avg_step_latency": 7.20
  }
}
```

---

## Conclusion

The profiling analysis demonstrates that:

1. **Parallel container creation scales efficiently** - Using `max_concurrent=16` achieves near-optimal creation times
2. **Throughput scales linearly** - Each additional container adds ~0.115 ops/s capacity
3. **Operation latencies remain stable** - No significant degradation up to 32 containers
4. **Container cleanup is the main bottleneck** - Sequential stopping wastes significant time

**Next Steps:**
1. Implement parallel container cleanup
2. Add adaptive health check waiting
3. Consider connection pooling for HTTP clients
4. Profile at 64+ containers to find upper scaling limits
