# Error Detection and Recovery System

## Motivation

AndroidWorld inference requires running trajectories across multiple Docker containers, each hosting an Android emulator. These distributed systems are prone to various failures:

- **Network issues**: Connection timeouts, HTTP errors
- **Container failures**: Server crashes, OOM kills
- **Emulator issues**: Frozen screens, process crashes

Without robust error recovery, a single failure can cause trajectory loss, leading to incomplete evaluation results.

**Goal**: Ensure all 234 test instances complete successfully with valid trajectories.

---

## Four-Layer Error Model

Errors can occur at four distinct layers in the system. Each layer requires specific detection and recovery mechanisms.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              HOST MACHINE                                │
│                                                                          │
│   ┌─────────────┐                                                        │
│   │   Trainer   │                                                        │
│   │ (Dispatcher)│                                                        │
│   └──────┬──────┘                                                        │
│          │                                                               │
│          ▼                                                               │
│   ┌─────────────┐         HTTP (reset/step)                              │
│   │RuntimeClient│ ─────────────────────────────────────────┐             │
│   └─────────────┘                                          │             │
│                                                            │             │
│         ▲                              ┌───────────────────┼───────────┐ │
│         │                              │     CONTAINER     │           │ │
│         │                              │                   ▼           │ │
│   ┌─────┴─────┐                        │  ┌────────────────────────┐   │ │
│   │  Layer 1  │◄───────────────────────┼──│  Layer 2: FastAPI      │   │ │
│   │  Network  │  Connection errors,    │  │  Server (server.py)    │   │ │
│   │           │  timeouts, HTTP 5xx    │  └───────────┬────────────┘   │ │
│   └───────────┘                        │              │                │ │
│                                        │              ▼                │ │
│                                        │  ┌────────────────────────┐   │ │
│                                        │  │  Layer 3: Environment  │   │ │
│                                        │  │  AndroidWorldEnv       │   │ │
│                                        │  │  (env.py)              │   │ │
│                                        │  └───────────┬────────────┘   │ │
│                                        │              │                │ │
│                                        │              ▼                │ │
│                                        │  ┌────────────────────────┐   │ │
│                                        │  │  Layer 4: Emulator     │   │ │
│                                        │  │  Android (QEMU)        │   │ │
│                                        │  │  - ADB connection      │   │ │
│                                        │  │  - gRPC connection     │   │ │
│                                        │  └────────────────────────┘   │ │
│                                        │                               │ │
│                                        └───────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘

Error Propagation:
  Layer 4 error → Layer 3 catches → Layer 2 returns HTTP 500 → Layer 1 detects
```

### Layer 1: Network

| Error Type | Cause | Detection |
|------------|-------|-----------|
| Connection refused | Container not started, port not exposed | `aiohttp.ClientConnectorError` |
| Connection reset | Network instability, server restart | `aiohttp.ServerDisconnectedError` |
| Timeout | Container overloaded, emulator slow | `asyncio.TimeoutError` |
| DNS failure | Configuration error | `aiohttp.ClientConnectorError` |

**Recovery**: Retry with exponential backoff (transient issues usually resolve quickly)

### Layer 2: Server (FastAPI)

| Error Type | Cause | Detection |
|------------|-------|-----------|
| HTTP 500 | Unhandled exception in endpoint | Response status code |
| HTTP 502/503/504 | Server overloaded or crashed | Response status code |
| Server OOM | Memory exhaustion | Connection refused after crash |
| Server deadlock | Thread/async blocking | Request timeout |

**Recovery**: Retry request; if persistent, container restart needed

### Layer 3: Environment (AndroidWorldEnv)

| Error Type | Cause | Detection |
|------------|-------|-----------|
| Screenshot failure | gRPC connection lost | Exception in `get_raw_observation()` |
| Blank screen | Emulator frozen or loading | `count_white_pixels()` > threshold |
| Action execution failure | Invalid action, emulator unresponsive | `perform_action()` returns False |
| Task initialization failure | Invalid task config, emulator issue | Exception in `reset()` |

**Recovery**: Internal retry (3 attempts); if persistent, emulator restart

### Layer 4: Emulator (Android)

| Error Type | Cause | Detection |
|------------|-------|-----------|
| Process crash | QEMU crash, resource exhaustion | `emulator_process.poll() is not None` |
| ADB disconnect | Emulator restart, port conflict | ADB devices command fails |
| gRPC disconnect | Emulator restart, service crash | gRPC calls fail |
| Frozen state | Emulator hang, infinite loop | Blank screen or slow response |

**Recovery**: Restart emulator process, replay action history to restore state

---

## Requirements

| Requirement | Description |
|-------------|-------------|
| **Completeness** | All test instances must have trajectories (no missing data) |
| **Efficiency** | Minimize recovery time; avoid unnecessary restarts |
| **Resilience** | Handle failures at all system layers independently |
| **Transparency** | Log all failures and recovery actions for debugging |

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         HOST                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Level 1: Step-Level Retry (RuntimeClient)               │  │
│  │  - 3 retries per HTTP request                            │  │
│  │  - Exponential backoff: 5s, 10s, 20s                     │  │
│  │  - 120s timeout per request                              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            ↓ (if fails)                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Level 2: Trajectory-Level Retry (Dispatcher)            │  │
│  │  - 3 retries per container                               │  │
│  │  - Full trajectory restart                               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            ↓ (if fails)                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Level 3: Container Switch (Dispatcher)                  │  │
│  │  - Up to 2 container switches                            │  │
│  │  - 10s delay before switch                               │  │
│  │  - Restart trajectory on new container                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Background: Health Monitor                              │  │
│  │  - Checks all containers every 15s                       │  │
│  │  - Auto-restarts unhealthy idle containers               │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────────┐
│                       CONTAINER                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Level 4: Emulator Recovery (Inside Container)           │  │
│  │  - Detects emulator crash via process/ADB check          │  │
│  │  - Auto-restarts emulator                                │  │
│  │  - Replays action history to restore state               │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

---

## Recovery Flow

```
Step N fails
     │
     ▼
┌─────────────────────────────┐
│ Level 1: HTTP Retry         │ ─── 3 attempts (5s, 10s, 20s)
│ Same request, same container│
└─────────────────────────────┘
     │ (still failing)
     ▼
┌─────────────────────────────┐
│ Level 2: Trajectory Retry   │ ─── 3 attempts (5s, 10s, 20s)
│ Restart from Step 1         │
│ Same container              │
└─────────────────────────────┘
     │ (still failing)
     ▼
┌─────────────────────────────┐
│ Level 3: Container Switch   │ ─── Up to 2 switches
│ Restart from Step 1         │
│ Different container         │
└─────────────────────────────┘
     │ (still failing)
     ▼
┌─────────────────────────────┐
│ Mark as Failed              │
│ Record in failure_history   │
└─────────────────────────────┘
```

---

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `STEP_MAX_RETRIES` | 3 | HTTP request retries |
| `STEP_RETRY_BASE_DELAY` | 5.0s | Base delay for HTTP retry backoff |
| `HTTP_TIMEOUT` | 120s | Timeout per HTTP request |
| `max_retries` | 3 | Trajectory retries per container |
| `max_container_switches` | 2 | Maximum container switches |
| `container_switch_delay` | 10s | Delay before switching container |
| Health monitor interval | 15s | Container health check frequency |

---

## Maximum Recovery Time

| Stage | Attempts | Max Time |
|-------|----------|----------|
| HTTP retries | 4 | 35s |
| Container 1 retries | 4 | 35s |
| Switch + Container 2 | 4 | 45s |
| Switch + Container 3 | 4 | 45s |
| **Total** | **16** | **~160s** |

---

## Key Files

| File | Component |
|------|-----------|
| `runtime_client.py` | HTTP retry, timeout, ErrorClassifier |
| `dispatchers.py` | Trajectory retry, container switching |
| `android_task.py` | Health monitor initialization |
| `container_manager.py` | Health check, container restart |
| `server.py` | `/health`, `/deep_health` endpoints |
| `env.py` | Emulator restart, action replay |

---

## Error Classification

Errors are classified by layer to apply appropriate recovery strategies:

| Layer | Error Types | Recovery Strategy |
|-------|-------------|-------------------|
| **Network** | Connection refused, timeout, reset | Quick retry (2s delay) |
| **Server** | HTTP 5xx, server crash | Medium retry (5s delay) |
| **Environment** | Screenshot fail, blank screen | Wait for internal recovery (10s) |
| **Emulator** | Process crash, ADB disconnect | Container switch recommended |

---

## Logging

All recovery actions are logged for debugging:

```
WARNING: Trajectory (0, 1) failed on env3 (attempt 2/4): Connection reset
INFO: Trajectory (0, 1) switching container (switch 1/2). Waiting 10s...
INFO: Trajectory (0, 1) now trying env7 (fresh restart from beginning)
INFO: Trajectory (0, 1) succeeded after 1 container switch(es) and 5 total attempts
```

---

## Health Endpoints

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `/health` | Basic liveness check | `{"status": "success"}` |
| `/deep_health` | Emulator responsiveness | `{"status": "healthy/degraded/unhealthy", "response_time": float}` |

---

## Summary

The error recovery system provides **multi-level protection**:

1. **Fast recovery** for transient issues (HTTP retry)
2. **Full restart** for persistent issues (trajectory retry)
3. **Container isolation** for unhealthy containers (container switch)
4. **Proactive healing** via background health monitor

This ensures **100% trajectory completion** for all test instances while minimizing recovery time.
