> **STATUS: ARCHIVED.** Comparison between the original AndroidWorld error
> handling and the SkyRL-Agent rewrite. The current production design is
> documented in [`../../error_recovery.md`](../../error_recovery.md).

# Error Detection & Recovery: Design Comparison

**Document Purpose**: Compare the error handling approaches between the original AndroidWorld implementation and the new SkyRL-Agent framework to facilitate discussion and gather feedback.

**Date**: January 2026  
**Author**: SkyRL-Agent Team  
**Reviewer**: Original AndroidWorld Team

---

## Executive Summary

We have refactored the error detection and recovery system for AndroidWorld inference. This document compares the two approaches to:

1. Identify gaps in the original design that motivated changes
2. Explain the new design decisions
3. Gather feedback on trade-offs (especially regarding speed)
4. Discuss potential improvements

**Key Change**: The new design prioritizes **zero infrastructure failures** over minimal overhead, trading some happy-path speed for comprehensive error recovery.

---

## 1. Architecture Overview

### Original Design (3-Layer)

```
┌─────────────────────────────────────────────────────────────────┐
│  _validate() - Inference Loop                                   │
│  • No try/except around ray.get()                               │
│  • No container health monitoring                               │
│  • No timeout for individual operations                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  EnvWorker (Ray Actor)                                          │
│  • Reset: try/except → restart container → retry once           │
│  • Step: NO try/except wrapper                                  │
│  • Graceful degradation on reset failure (is_done=True)         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  AndroidWorldHostEnv                                            │
│  • Docker lifecycle management                                  │
│  • HTTP requests to container (no retry)                        │
│  • Health check only at startup                                 │
└─────────────────────────────────────────────────────────────────┘
```

### New Design (5-Layer)

```
┌─────────────────────────────────────────────────────────────────┐
│  Dispatcher (async_fix_pool_retry)                              │
│  • Error classification (dead container / context / transient)  │
│  • Two-level retry: per-container + container switching         │
│  • Pre-flight container health check                            │
│  • Critical failure detection (stops batch)                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  AndroidAgentRunner                                             │
│  • Wires dispatcher callbacks                                   │
│  • Records retry metadata on trajectories                       │
│  • Masks loss for error trajectories                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  ContainerManager                                               │
│  • State machine: HEALTHY → IN_USE → UNHEALTHY → RESTARTING     │
│  • Background HealthMonitor (30s interval)                      │
│  • Background RestartWorker (auto-recovery)                     │
│  • BackupPool (hot standby containers)                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RuntimeClient                                                  │
│  • Step-level retry (3 attempts, 5s delay)                      │
│  • HTTP timeout (120s)                                          │
│  • Error layer classification                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Error Coverage Comparison

### Original Design

| Error Type | Detection | Recovery | Outcome |
|------------|-----------|----------|---------|
| Reset fails (1st attempt) | ✅ try/except | ✅ Restart + retry | Continues |
| Reset fails (2nd attempt) | ✅ try/except | ⚠️ Graceful exit | 0 reward trajectory |
| **Step HTTP fails** | ❌ No handler | ❌ None | **CRASH entire inference** |
| Action parse fails | ✅ try/except | ✅ Graceful | Episode ends |
| Screenshot null | ✅ Null check | ✅ Graceful | Episode ends |
| Container frozen | ❌ No detection | ❌ None | **Blocks forever** |
| Context length exceeded | ❌ No detection | ❌ None | Crashes |

### New Design

| Error Type | Detection | Recovery | Outcome |
|------------|-----------|----------|---------|
| Reset fails | ✅ try/except | ✅ Multi-retry + switch | Continues |
| Step HTTP fails | ✅ try/except | ✅ Retry 3x | Continues |
| Container dead | ✅ Pattern match | ✅ Fast-fail + switch | Continues |
| Container frozen | ✅ quick_ping | ✅ Pre-check + switch | Continues |
| Context length exceeded | ✅ Pattern match | ⚠️ Fast-fail | 0 reward, loss masked |
| All retries exhausted | ✅ Counter | ⚠️ Critical failure | Batch stops |

---

## 3. Critical Gap in Original Design

**Location**: `mobile_agent.py` lines 446-448

```python
# Original code - step() method
payload = {'action': action, 'thought': thought}
observation, reward, terminated, truncated, info = self.env.step(payload)  # ← NO try/except
self.reward = reward
```

**Problem**: If the HTTP request fails mid-trajectory (container dies, network timeout, etc.):
1. Exception propagates to Ray actor
2. Ray actor crashes
3. `ray.get()` in `_validate()` raises exception
4. **Entire inference batch fails**

**Impact**: A single transient network error can abort a multi-hour inference run.

**Question for Original Team**: Was this intentional? Is there Ray-level recovery we're not seeing?

---

## 4. Retry Strategy Comparison

### Original: Single Retry (Reset Only)

```
Reset fails
    └── Restart container (wait up to 300s)
        └── Retry once
            └── Success → continue
            └── Fail → is_done=True, reward=0
                        
Step fails
    └── CRASH (no recovery)
```

### New: Two-Level Retry with Container Switching

```
Step fails
    └── Retry 3x with 5s delay
        └── All fail → bubble up to trajectory level

Trajectory fails on container X
    └── Retry 5x on same container
        └── Dead container detected? → fast-fail
        └── All fail → switch container

Container switch (up to 10 times)
    └── Get different container from pool
    └── Restart trajectory from beginning
    └── Mark old container UNHEALTHY (background restart)

All switches exhausted
    └── CRITICAL FAILURE → stop batch
    └── (This should never happen with enough containers)
```

---

## 5. Speed & Overhead Analysis

### Happy Path (No Errors)

| Metric | Original | New |
|--------|----------|-----|
| Pre-flight check | None | quick_ping (≤10s timeout) |
| Background threads | None | 2 (HealthMonitor, RestartWorker) |
| Network calls per trajectory | 0 extra | 1 (quick_ping) |
| Memory overhead | None | BackupPool containers |

**Estimated overhead**: ~0.1-0.5s per trajectory start (quick_ping)

### On Failure

| Scenario | Original | New |
|----------|----------|-----|
| Single transient step error | CRASH | 5s delay + retry |
| Container dies mid-trajectory | CRASH or hang | ~10s (fast-fail + switch) |
| Container frozen | Infinite hang | 10s timeout → switch |
| Reset fails twice | 300s + 0 reward | 5-10s + switch + retry |

### Background Resource Usage

| Resource | Original | New |
|----------|----------|-----|
| CPU (background monitors) | 0% | ~0.1% |
| Network (health checks) | 0 | 1 call/container/30s |
| Memory (backup pool) | 0 | 4 extra containers (configurable) |

---

## 6. Configuration (New Design)

```yaml
# From verl_android_inference.yaml

env:
  pool_size: 16        # Active containers
  buffer_size: 4       # Hot standby (instant failover)

dispatcher:
  type: async_fix_pool
  max_retries: 5              # Retries per container
  max_container_switches: 10  # Container switches allowed
  retry_base_delay: 2.0       # Delay between retries
  container_switch_delay: 5.0 # Delay when switching
```

**Tuning for speed (if infrastructure is stable)**:
```yaml
dispatcher:
  max_retries: 2              # Reduce retries
  max_container_switches: 2   # Reduce switches
  retry_base_delay: 1.0       # Shorter delay

env:
  buffer_size: 0              # Disable backup pool
```

---

## 7. Failure Trajectory Handling

### Original
- Reset failure → 0 reward trajectory recorded
- Step failure → **No trajectory recorded** (crash)

### New
- All failures → 0 reward trajectory recorded
- Error trajectories have loss masked (don't train on infrastructure failures)
- Explicit tracking of failure reasons:

```python
# From android_runner.py
mask_out_reason = [
    "CONTEXT_WINDOW_EXCEEDED",
    "error_runtime",
    "error_evaluation", 
    "max_iterations_reached",
    "BAD_LLM_RESPONSE",
    "stuck_in_a_loop",
    "cmd_timeout",
]
```

---

## 8. Questions for Discussion

### Design Philosophy

1. **Was the step error handling intentional?** The lack of try/except around `env.step()` seems like a potential oversight. Was there a reason for this?

2. **Is "fail fast" preferred?** The original design crashes on step errors rather than recording a failure trajectory. Is crashing preferable in some scenarios?

3. **Ray actor recovery**: Does Ray have built-in actor recovery that we're not leveraging? Could Ray restart crashed EnvWorkers automatically?

### Speed Concerns

4. **Is the quick_ping overhead acceptable?** We add ~0.1-0.5s per trajectory for pre-flight health check. Is this too much?

5. **Background monitor frequency**: We check health every 30s. Is this too frequent? Too infrequent?

6. **Backup pool size**: We keep 4 hot standby containers. Is the memory cost justified?

### Edge Cases

7. **Container frozen detection**: The original design has no timeout on step(). Have you seen containers freeze mid-trajectory in practice?

8. **Context length errors**: How often do trajectories exceed context limits? We detect this pattern and fast-fail. Is this the right approach?

### Missing Features

9. **What error scenarios have you encountered** that neither design handles well?

10. **Proactive restart**: The training loop has periodic container restart (`restart_frequency`). Should inference have this too?

---

## 9. Proposed Improvements (Open for Discussion)

### For Original Design (Minimal Changes)

```python
# Add try/except around step in mobile_agent.py
def step(self, prediction):
    # ... action parsing ...
    
    try:
        observation, reward, terminated, truncated, info = self.env.step(payload)
    except Exception as e:
        print(f"Step failed: {e}")
        self.is_done = True
        self.reward = 0.0
        return {"is_done": True, "obs_messages": None, ...}
    
    self.reward = reward
    # ... rest of step ...
```

### For New Design (Speed Optimization)

```python
# Disable pre-flight check if infrastructure is stable
dispatcher_cfg = {
    "quick_ping": None,  # Skip pre-check
    "max_retries": 2,     # Fewer retries
}
```

---

## 10. Summary

| Aspect | Original | New | Trade-off |
|--------|----------|-----|-----------|
| **Speed (happy path)** | ✅ Fastest | Slightly slower | ~0.1-0.5s overhead |
| **Step error handling** | ❌ Crashes | ✅ Recovered | Reliability vs simplicity |
| **Container switching** | ❌ None | ✅ Up to 10x | Utilization vs speed |
| **Health monitoring** | ❌ None | ✅ Background | Resource usage |
| **Complexity** | ✅ Simple | More complex | Maintainability |
| **Zero infra failures** | ❌ Not guaranteed | ✅ Goal | Robustness |

**Our Position**: For long-running inference jobs (hours), the overhead is negligible compared to the cost of a mid-run crash. We prioritize completing all test instances over minimal latency.

**We Welcome Feedback** on whether this trade-off is appropriate for your use cases.

---

## Appendix: File Locations

### Original Design
- Entry: `aw_g_original/examples/aw_tests/eval.sh`
- Trainer: `aw_g_original/verl/trainer/ppo/ray_trainer.py`
- EnvWorker: `aw_g_original/verl/trainer/mobile_agent.py`
- HostEnv: `aw_g_original/verl/trainer/androidworld_env.py`
- Server: `docker/android/server/server.py`

### New Design
- Entry: `skyrl-agent/examples/run_verl/verl_android_inference.sh`
- Config: `skyrl-agent/examples/run_verl/verl_android_inference.yaml`
- Trainer: `skyrl-agent/skyrl_agent/integrations/verl/verl_trainer.py`
- Dispatcher: `skyrl-agent/skyrl_agent/dispatcher/dispatchers.py`
- Runner: `skyrl-agent/skyrl_agent/agents/android/android_runner.py`
- ContainerManager: `skyrl-agent/skyrl_agent/runtime/android/container_manager.py`
- RuntimeClient: `skyrl-agent/skyrl_agent/runtime/android/runtime_client.py`
