# Container Pool Profiling & Pressure Testing

This directory contains profiling and testing tools for the AndroidWorld container pool and dispatcher system.

## Contents

| File | Description |
|------|-------------|
| `profile_container_pool.py` | Real Docker container performance profiling |
| `pressure_test_dispatcher.py` | Mocked dispatcher stress testing for error recovery |
| `run_profiling.sh` | Shell script for container profiling presets |
| `run_pressure_test.sh` | Shell script for pressure test presets |
| `README.md` | This documentation |

---

## Part 1: Container Pool Profiling

The container profiling script measures performance characteristics of the container pool system:

- **Container Creation**: Time to start Docker containers with Android emulators (sequential or parallel)
- **Allocation/Release**: Latency of container pool management operations
- **Reset/Step Operations**: API call latency for environment interactions (all action types)
- **Concurrent Throughput**: Operations per second with parallel agents

## Quick Start

```bash
cd skyrl-agent

# Quick test (1 container, skip concurrent test)
./tests/profiling/run_profiling.sh --quick

# Default test (pool sizes 1, 2, 4, sequential creation)
./tests/profiling/run_profiling.sh

# Full test (pool sizes 1, 2, 4, 8, 16)
./tests/profiling/run_profiling.sh --full

# Parallel creation (faster for large pools)
./tests/profiling/run_profiling.sh --parallel

# Parallel full test (pool sizes 4, 8, 16 with parallel creation)
./tests/profiling/run_profiling.sh --parallel-full
```

## Usage

### Using the Shell Script

```bash
# Quick mode - single container, no concurrent test
./tests/profiling/run_profiling.sh --quick

# Default mode - pool sizes 1, 2, 4 (sequential creation)
./tests/profiling/run_profiling.sh

# Full mode - pool sizes 1, 2, 4, 8, 16 with 60s concurrent test
./tests/profiling/run_profiling.sh --full

# Parallel mode - pool sizes 4, 8 with parallel creation (faster)
./tests/profiling/run_profiling.sh --parallel

# Parallel full mode - pool sizes 4, 8, 16 with parallel creation
./tests/profiling/run_profiling.sh --parallel-full

# Pass additional arguments
./tests/profiling/run_profiling.sh --output /path/to/results.json
```

### Using Python Directly

```bash
# Enable Docker tests (required)
export RUN_DOCKER_TESTS=true

# Run with default settings (sequential creation)
uv run python tests/profiling/profile_container_pool.py

# Custom pool sizes
uv run python tests/profiling/profile_container_pool.py --pool-sizes 2 4 8

# Skip concurrent test for faster results
uv run python tests/profiling/profile_container_pool.py --pool-sizes 1 2 --skip-concurrent

# Use parallel creation for faster pool startup
uv run python tests/profiling/profile_container_pool.py \
    --pool-sizes 4 8 16 \
    --parallel-creation \
    --max-concurrent 4 \
    --initial-wait 30

# Custom concurrent test duration
uv run python tests/profiling/profile_container_pool.py --concurrent-duration 60

# Specify output file
uv run python tests/profiling/profile_container_pool.py --output results.json
```

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--pool-sizes` | `1 2 4` | Space-separated list of pool sizes to test |
| `--docker-image` | `androidworld:v8` | Docker image name (or `$ANDROID_DOCKER_IMAGE`) |
| `--temp-dir` | `/tmp/profile_containers` | Temp directory for logs |
| `--output` | Auto-generated | Output JSON file path |
| `--skip-concurrent` | `false` | Skip concurrent throughput test |
| `--concurrent-duration` | `30` | Duration of concurrent test in seconds |
| `--parallel-creation` | `false` | Use bounded parallel pool creation |
| `--max-concurrent` | `4` | Max concurrent container creations (parallel mode) |
| `--initial-wait` | `45` | Initial emulator boot wait in seconds (try 30 for faster) |
| `--skip-cleanup` | `false` | Skip cleanup of stale containers before profiling |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `RUN_DOCKER_TESTS=true` | **Required** - Enable Docker-based tests |
| `ANDROID_DOCKER_IMAGE` | Docker image name (default: `androidworld:v8`) |
| `PROFILE_TEMP_DIR` | Temp directory for logs |

## Metrics Collected

### Per Pool Size

| Metric | Unit | Description |
|--------|------|-------------|
| `total_creation_time` | seconds | Time to create entire pool |
| `avg_creation_time_per_container` | seconds | Average per-container startup (~56s typical) |
| `creation_mode` | string | "sequential" or "parallel" |
| `max_concurrent` | int | Max concurrent creations (parallel mode) |
| `initial_wait` | seconds | Initial emulator boot wait used |
| `avg_allocation_latency` | seconds | Time to get container from queue |
| `avg_release_latency` | seconds | Time to return container to queue |
| `avg_reset_latency` | seconds | Time for `/reset` API call |
| `avg_step_latency` | seconds | Overall average for `/step` API call |
| `avg_step_latency_by_type` | dict | Per-action-type step latencies (click, scroll, etc.) |
| `concurrent_ops_per_second` | ops/s | Throughput with parallel workers |

### Action Types Profiled

The profiler tests 7 unique action types for realistic latency measurements (~28 steps per pool size):

| Action Type | Description |
|-------------|-------------|
| `wait` | No-op action |
| `click` | Tap at coordinates |
| `scroll` | Scroll down |
| `navigate_home` | Press home button |
| `navigate_back` | Press back button |
| `input_text` | Type text input |
| `long_press` | Long press at coordinates |

### Expected Values

| Metric | Expected Range | Notes |
|--------|----------------|-------|
| Container creation | 50-70s each | Includes emulator boot + health check |
| Allocation latency | <1ms | Queue operation only |
| Release latency | <10ms | Includes health check |
| Reset latency | 1-5s | Depends on task complexity |
| Step latency | 0.5-2s | Includes screenshot capture |

## Output Format

### Console Output

```
========================================================================================================================
PROFILING SUMMARY
========================================================================================================================
 Pool Size | Mode       | Creation (s) | Per Container (s) | Alloc (ms) | Release (ms) | Reset (s) | Step (s) | Throughput
----------------------------------------------------------------------------------------------------------------------------
     4     |   seq      |    224.5     |       56.1        |    0.15    |     8.21     |   2.15    |   0.92   |    3.21
     8     | par(4)     |    125.3     |       15.7        |    0.18    |     8.45     |   2.08    |   0.89   |    6.45
========================================================================================================================

Step Latency by Action Type (seconds):
--------------------------------------------------------------------------------
Action Type          | Pool   4 | Pool   8
--------------------------------------------------------------------------------
click                |    0.892 |    0.885
input_text           |    1.234 |    1.198
long_press           |    0.956 |    0.948
navigate_back        |    0.445 |    0.438
navigate_home        |    0.412 |    0.405
scroll               |    0.678 |    0.665
wait                 |    0.312 |    0.305
--------------------------------------------------------------------------------

Scaling Analysis:
  Pool 4 -> 8: Creation scales 0.6x (vs 2.0x linear), Efficiency: 358%
    Throughput scales 2.01x
```

### JSON Output

Results are saved to `$PROFILE_TEMP_DIR/profile_results_YYYYMMDD_HHMMSS.json`:

```json
{
  "timestamp": "2026-01-20T12:00:00.000000",
  "results": [
    {
      "pool_size": 4,
      "total_creation_time": 224.5,
      "avg_creation_time_per_container": 56.1,
      "creation_mode": "sequential",
      "max_concurrent": 1,
      "initial_wait": 45.0,
      "allocation_latencies": [0.00012, 0.00015],
      "avg_allocation_latency": 0.00013,
      "reset_latencies": [2.1, 1.8],
      "avg_reset_latency": 1.95,
      "step_latencies_by_type": {
        "wait": [0.31, 0.32],
        "click": [0.88, 0.91],
        "scroll": [0.67, 0.69],
        "navigate_home": [0.41, 0.42],
        "navigate_back": [0.44, 0.45],
        "input_text": [1.23, 1.25],
        "long_press": [0.95, 0.96]
      },
      "avg_step_latency_by_type": {
        "wait": 0.315,
        "click": 0.895,
        "scroll": 0.680
      },
      "avg_step_latency": 0.72,
      "concurrent_ops_per_second": 3.21,
      "errors": []
    }
  ]
}
```

## Prerequisites

1. **Docker** - Docker daemon must be running
2. **KVM** - `/dev/kvm` required for Android emulator
3. **Docker Image** - `androidworld:v8` image must be built
4. **Disk Space** - ~2GB per container for logs/temp files

## Troubleshooting

### "Docker not available"

Ensure Docker daemon is running:
```bash
sudo systemctl start docker
# or
docker ps
```

### "KVM not available"

KVM is required for Android emulator. Check:
```bash
ls -la /dev/kvm
```

If missing, you may need to enable virtualization in BIOS or run on a VM with nested virtualization.

### Container creation timeout

The default timeout is 600s (10 minutes). If containers fail to become healthy:

1. Check Docker logs: `docker logs env0`
2. Verify image is correct: `docker images | grep androidworld`
3. Check disk space: `df -h`

### Port conflicts

If you see port allocation errors, there may be stale containers:
```bash
# List running containers
docker ps

# Remove stale env containers
docker rm -f $(docker ps -aq --filter "name=env*")
```

## Interpreting Results

### Creation Time

**Sequential Mode** (default):
- Container creation is sequential due to port allocation locking
- Expect linear scaling with pool size
- ~56s per container (45s emulator boot + 10s health check)

**Parallel Mode** (`--parallel-creation`):
- Uses bounded parallelism (controlled by `--max-concurrent`)
- Pre-allocates all ports atomically before starting containers
- Can achieve 3-6x speedup for large pools (e.g., 16 containers)
- Reduced initial wait (`--initial-wait 30`) can further improve speed

| Pool Size | Sequential | Parallel (4 concurrent) | Speedup |
|-----------|------------|-------------------------|---------|
| 4         | ~224s      | ~120s                   | ~1.9x   |
| 8         | ~448s      | ~180s                   | ~2.5x   |
| 16        | ~896s      | ~240s                   | ~3.7x   |

### Concurrent Throughput

Measures how well the system utilizes multiple containers:
- Should scale roughly linearly with pool size
- Bottlenecks: emulator speed, network, disk I/O

### Allocation Latency

Should be sub-millisecond (just queue operations). If high:
- Check health monitoring overhead
- Consider increasing health check interval

## Integration with CI

```yaml
# Example GitHub Actions job
profiling:
  runs-on: self-hosted  # Needs KVM support
  steps:
    - uses: actions/checkout@v4
    - name: Run profiling
      run: |
        cd skyrl-agent
        RUN_DOCKER_TESTS=true ./tests/profiling/run_profiling.sh --quick
    - name: Upload results
      uses: actions/upload-artifact@v4
      with:
        name: profiling-results
        path: /tmp/profile_containers/*.json
```

---

## Part 2: Dispatcher Pressure Testing

The pressure test script simulates many mocked trajectories to test the dispatcher's error detection and recovery mechanisms **without requiring actual Docker containers**.

### What It Tests

1. **Error Detection & Classification**
   - Dead container errors (connection refused, timeout, etc.)
   - Context length errors (prompt too long)
   - Transient errors (temporary failures)

2. **Recovery Mechanisms**
   - Step-level retries with backoff
   - Container switching on failure
   - Fast-fail for deterministic errors
   - Backup pool usage

3. **Concurrency & Robustness**
   - Multiple concurrent trajectories
   - Container state management
   - Recovery callback integration

### Quick Start

```bash
cd skyrl-agent

# Quick test (8 trajectories, low failure rate)
./tests/profiling/run_pressure_test.sh quick

# Medium test (24 trajectories, moderate failure rate)
./tests/profiling/run_pressure_test.sh medium

# Stress test (50 trajectories, high failure rate)
./tests/profiling/run_pressure_test.sh stress

# Unit tests only (error classification verification)
./tests/profiling/run_pressure_test.sh unit
```

### Using Python Directly

```bash
# Basic test
uv run python tests/profiling/pressure_test_dispatcher.py

# Custom configuration
uv run python tests/profiling/pressure_test_dispatcher.py \
    --num-trajectories 10 \
    --num-instances 5 \
    --num-containers 4 \
    --failure-rate 0.3 \
    --dead-container-rate 0.1 \
    --context-error-rate 0.05 \
    --seed 42

# Stress mode with timing chaos
uv run python tests/profiling/pressure_test_dispatcher.py \
    --num-trajectories 20 \
    --failure-rate 0.5 \
    --stress-mode

# Save results to JSON
uv run python tests/profiling/pressure_test_dispatcher.py \
    --output results.json
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--num-trajectories` | 5 | Trajectories per instance |
| `--num-instances` | 4 | Number of task instances |
| `--num-containers` | 4 | Number of mock containers |
| `--failure-rate` | 0.2 | Base failure rate (0-1) |
| `--dead-container-rate` | 0.1 | Rate of dead container errors |
| `--context-error-rate` | 0.05 | Rate of context length errors |
| `--max-retries` | 3 | Max retries per container |
| `--max-container-switches` | 2 | Max container switches |
| `--stress-mode` | false | Enable timing chaos for stress testing |
| `--verbose` | false | Enable debug logging |
| `--seed` | None | Random seed for reproducibility |
| `--run-unit-tests` | false | Run only error classification tests |
| `--output` | None | Output JSON file path |

### Test Scenarios

| Scenario | Trajectories | Failure Rate | Dead Rate | Context Rate | Purpose |
|----------|-------------|--------------|-----------|--------------|---------|
| `quick` | 8 | 0.15 | 0.05 | 0.02 | Fast smoke test |
| `medium` | 24 | 0.25 | 0.1 | 0.03 | Standard testing |
| `stress` | 50 | 0.4 | 0.15 | 0.05 | Stress testing with chaos |
| `large` | 100 | 0.2 | 0.08 | 0.02 | Scale testing |

### Sample Output

```
======================================================================
PRESSURE TEST RESULTS
======================================================================

[1] Overall Summary
--------------------------------------------------
  Total Trajectories:      24
  Successful:              23 (95.8%)
  Failed:                  1
  Context Errors:          1
  Execution Time:          2.15s
  Avg Trajectory Time:     89.6ms

[2] Recovery Metrics
--------------------------------------------------
  Total Container Switches:    3
  Total Retry Attempts:        35
  Recovered from Dead:         4
  Recovered from Transient:    18

[3] Container Statistics
--------------------------------------------------
Env ID   Total      Success    Failed     Dead     Context    Transient  Restarts  
-----------------------------------------------------------------------------------
       0         25         20          5        1          0          4          1
       1         22         19          3        0          0          3          0
       2         28         25          3        0          1          2          0
       3         20         18          2        1          0          1          1

[6] Error Classification Verification
--------------------------------------------------
  Dead container errors classified correctly: True
  Context length errors classified correctly: True

======================================================================
RESULT: EXCELLENT - High success rate with good recovery
======================================================================
```

### Error Classification

The test verifies that error classification works correctly:

**Dead Container Errors** (fast-fail to container switch):
- "cannot connect", "connection refused"
- "server disconnected", "connection reset by peer"
- "no route to host", "network is unreachable"
- "connection timed out", "failed to establish a new connection"

**Context Length Errors** (deterministic failure, no retry):
- "maximum model length", "max_model_len"
- "context window exceeded", "prompt is too long"
- "exceeds the maximum"

**Transient Errors** (retry on same container):
- HTTP 500 errors, timeout errors
- Emulator/ADB errors, action execution failures

### Integration with CI

```yaml
# Example GitHub Actions job
pressure-test:
  runs-on: ubuntu-latest  # No Docker required!
  steps:
    - uses: actions/checkout@v4
    - name: Run pressure test
      run: |
        cd skyrl-agent
        uv run python tests/profiling/pressure_test_dispatcher.py \
          --num-trajectories 5 \
          --num-instances 10 \
          --failure-rate 0.25 \
          --seed 42
```
