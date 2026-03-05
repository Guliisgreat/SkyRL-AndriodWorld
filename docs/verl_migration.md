# verl 0.5 → 0.6.1 Migration Guide for SkyRL-Agent

## Table of Contents
1. [Conceptual Foundation](#1-conceptual-foundation)
2. [verl AgentLoop Architecture Evolution](#2-verl-agentloop-architecture-evolution)
3. [Dispatcher vs verl's AgentLoop](#3-dispatcher-vs-verls-agentloop)
4. [Migration Summary](#4-migration-summary)

---

## 1. Conceptual Foundation

In reinforcement learning with LLMs, the system has multiple layers:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RL Training System                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Training Layer (PPO/GRPO)                                             │ │
│  │  - Policy optimization, reward computation, weight updates             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                              ▲                                               │
│                              │ trajectories + rewards                        │
│                              │                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Agent Layer (verl AgentLoop / SkyRL-Agent)     ◄── THIS DOCUMENT     │ │
│  │  - Multi-turn agent execution                                          │ │
│  │  - Environment interaction                                             │ │
│  │  - LLM inference orchestration                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                              ▲                                               │
│                              │ tokens                                        │
│                              │                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Inference Layer (vLLM / SGLang)                                       │ │
│  │  - Fast LLM inference, KV caching, batching                            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

The **Agent Layer** is the focus of this document. It orchestrates:
- How a batch of agent trajectories is processed
- How agents interact with LLM inference engines (vLLM/SGLang)
- How parallelism is achieved across multiple trajectories

---

## 2. verl AgentLoop Architecture Evolution

### 2.1 verl 0.5.x: Batch of Trajectories Flow

In verl 0.5.x, a batch of agent trajectories interacts directly with a single vLLM engine via `AsyncvLLMServerRegular`:

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                    verl 0.5.x: Batch of Trajectories → vLLM Engine                   │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│   Input: Batch of N agent trajectories                                              │
│   ═══════════════════════════════════════                                           │
│                                                                                      │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │                         Agent Logic (ToolAgent)                              │   │
│   │                                                                               │   │
│   │   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐               │   │
│   │   │  Traj 0   │  │  Traj 1   │  │  Traj 2   │  │  Traj N   │               │   │
│   │   │  Agent    │  │  Agent    │  │  Agent    │  │  Agent    │   ...         │   │
│   │   │(LangGraph)│  │(LangGraph)│  │(LangGraph)│  │(LangGraph)│               │   │
│   │   └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘               │   │
│   │         │              │              │              │                      │   │
│   └─────────┼──────────────┼──────────────┼──────────────┼──────────────────────┘   │
│             │              │              │              │                          │
│             └──────────────┴──────┬───────┴──────────────┘                          │
│                                   │ generate() calls                                 │
│                                   ▼                                                  │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │                      AsyncvLLMServerRegular                                  │   │
│   │   ─────────────────────────────────────────────────────────────────────────  │   │
│   │   • Direct wrapper around vLLM engine                                        │   │
│   │   • No load balancing (single instance)                                      │   │
│   │   • All trajectory requests → same server                                    │   │
│   └─────────────────────────────────┬───────────────────────────────────────────┘   │
│                                     │                                                │
│                                     ▼                                                │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │                        vLLM Engine (Single Instance)                         │   │
│   └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│   Limitations:                                                                       │
│   ✗ No AgentLoopManager (no batch orchestration)                                    │
│   ✗ No AgentLoopWorker (no Ray-based parallelism)                                   │
│   ✗ No AsyncLLMServerManager (no load balancing)                                    │
│   ✗ No RolloutReplica (no multi-backend abstraction)                                │
│   ✗ No SGLang support                                                               │
│   ✗ No wake_up/sleep lifecycle                                                      │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 verl 0.6.1: Batch of Trajectories Flow

verl 0.6.1 introduces a **layered architecture** with `AgentLoopManager`, `AgentLoopWorker`, `AsyncLLMServerManager`, and `RolloutReplica`:

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                 verl 0.6.1: Batch of Trajectories → vLLM/SGLang Engines              │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│   Input: Batch of N agent trajectories                                              │
│   ═══════════════════════════════════════                                           │
│                                                                                      │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │                          AgentLoopManager                                    │   │
│   │   ─────────────────────────────────────────────────────────────────────────  │   │
│   │   • Splits batch into chunks for parallel processing                        │   │
│   │   • Manages AgentLoopWorker lifecycle                                        │   │
│   │   • Coordinates wake_up/sleep for colocate mode                              │   │
│   │   • Aggregates results from all workers                                      │   │
│   └─────────────────────────────────┬───────────────────────────────────────────┘   │
│                                     │ dispatches batch chunks                        │
│                                     ▼                                                │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │                    AgentLoopWorker (Ray Actors)                              │   │
│   │                                                                               │   │
│   │   ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐ │   │
│   │   │  AgentLoopWorker 0  │  │  AgentLoopWorker 1  │  │  AgentLoopWorker K  │ │   │
│   │   │    (Ray Actor)      │  │    (Ray Actor)      │  │    (Ray Actor)      │ │   │
│   │   │ ┌─────────────────┐ │  │ ┌─────────────────┐ │  │ ┌─────────────────┐ │ │   │
│   │   │ │ Traj 0..M       │ │  │ │ Traj M+1..2M    │ │  │ │ Traj ...N       │ │ │   │
│   │   │ │ Agent Logic     │ │  │ │ Agent Logic     │ │  │ │ Agent Logic     │ │ │   │
│   │   │ │ (LangGraph)     │ │  │ │ (LangGraph)     │ │  │ │ (LangGraph)     │ │ │   │
│   │   │ └─────────────────┘ │  │ └─────────────────┘ │  │ └─────────────────┘ │ │   │
│   │   └──────────┬──────────┘  └──────────┬──────────┘  └──────────┬──────────┘ │   │
│   │              │                        │                        │            │   │
│   └──────────────┼────────────────────────┼────────────────────────┼────────────┘   │
│                  └────────────────────────┼────────────────────────┘                │
│                                           │ all workers share                       │
│                                           ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │                       AsyncLLMServerManager                                  │   │
│   │   ─────────────────────────────────────────────────────────────────────────  │   │
│   │   • Load balances requests across replicas                                   │   │
│   │   • Least-requests routing algorithm                                         │   │
│   │   • Sticky sessions (request_id → replica for prefix caching)                │   │
│   └─────────────────────────────────┬───────────────────────────────────────────┘   │
│                                     │ routes to best available replica              │
│                                     ▼                                                │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │               RolloutReplica (vLLMReplica / SGLangReplica)                   │   │
│   │                                                                               │   │
│   │   ┌───────────────────────┐  ┌───────────────────────┐  ┌─────────────────┐ │   │
│   │   │     vLLMReplica 0     │  │     vLLMReplica 1     │  │  SGLangReplica  │ │   │
│   │   │   • init_hybrid()     │  │   • init_hybrid()     │  │ • init_hybrid() │ │   │
│   │   │   • wake_up() / sleep │  │   • wake_up() / sleep │  │ • wake_up/sleep │ │   │
│   │   │   • generate()        │  │   • generate()        │  │ • generate()    │ │   │
│   │   └───────────┬───────────┘  └───────────┬───────────┘  └────────┬────────┘ │   │
│   └───────────────┼──────────────────────────┼───────────────────────┼──────────┘   │
│                   │                          │                       │              │
│                   ▼                          ▼                       ▼              │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │            Inference Engines (vLLM / SGLang - Multiple Instances)            │   │
│   │                                                                               │   │
│   │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │   │
│   │   │  vLLM Engine 0  │  │  vLLM Engine 1  │  │  SGLang Engine  │             │   │
│   │   └─────────────────┘  └─────────────────┘  └─────────────────┘             │   │
│   └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Side-by-Side Comparison

```
┌──────────────────────────────────────────┐    ┌──────────────────────────────────────────┐
│            verl 0.5.x                    │    │            verl 0.6.1                    │
├──────────────────────────────────────────┤    ├──────────────────────────────────────────┤
│                                          │    │                                          │
│        (No Manager/Orchestrator)         │    │         AgentLoopManager                 │
│                                          │    │    • Orchestrates batch processing       │
│  ┌────────────────────────────────────┐  │    │    • Manages worker lifecycle            │
│  │   Batch of Trajectories            │  │    │  ┌────────────────────────────────────┐  │
│  │   ┌───────┐ ┌───────┐ ┌───────┐    │  │    │  │   Batch split across workers      │  │
│  │   │Traj 0 │ │Traj 1 │ │Traj N │    │  │    │  └────────────────┬───────────────────┘  │
│  │   │Agent  │ │Agent  │ │Agent  │    │  │    │                   │                      │
│  │   └───┬───┘ └───┬───┘ └───┬───┘    │  │    │         AgentLoopWorker (Ray)            │
│  └───────┼─────────┼─────────┼────────┘  │    │  ┌────────────────┼───────────────────┐  │
│          │         │         │           │    │  │ ┌────────┐ ┌───┴────┐ ┌────────┐  │  │
│          └─────────┼─────────┘           │    │  │ │Worker 0│ │Worker 1│ │Worker K│  │  │
│                    │                     │    │  │ │Traj0..M│ │TrajM.. │ │Traj..N │  │  │
│         (No Load Balancer)               │    │  │ └────┬───┘ └────┬───┘ └────┬───┘  │  │
│                    │                     │    │  └──────┼──────────┼──────────┼──────┘  │
│  ┌─────────────────▼──────────────────┐  │    │         └──────────┼──────────┘         │
│  │     AsyncvLLMServerRegular         │  │    │                    │                    │
│  │     • Direct vLLM wrapper          │  │    │       AsyncLLMServerManager             │
│  │     • Single instance              │  │    │    • Load balancing across replicas     │
│  │     • No abstraction               │  │    │    • Sticky sessions for caching        │
│  └─────────────────┬──────────────────┘  │    │  ┌─────────────────┼───────────────────┐│
│                    │                     │    │  │                 │                   ││
│                    ▼                     │    │  │      RolloutReplica Layer           ││
│  ┌────────────────────────────────────┐  │    │  │  ┌──────────┐ ┌─┴────────┐         ││
│  │                                    │  │    │  │  │vLLMRepl 0│ │vLLMRepl 1│ ...     ││
│  │     vLLM Engine (Single)           │  │    │  │  │SGLangRepl│ │          │         ││
│  │                                    │  │    │  │  └────┬─────┘ └────┬─────┘         ││
│  └────────────────────────────────────┘  │    │  └───────┼────────────┼───────────────┘│
│                                          │    │          ▼            ▼                │
│  MISSING:                                │    │  ┌────────────────────────────────────┐│
│  ✗ AgentLoopManager                      │    │  │  vLLM/SGLang Engines (Multiple)   ││
│  ✗ AgentLoopWorker                       │    │  └────────────────────────────────────┘│
│  ✗ AsyncLLMServerManager                 │    │                                        │
│  ✗ RolloutReplica                        │    │  NEW COMPONENTS:                       │
│  ✗ SGLang support                        │    │  ✓ AgentLoopManager                    │
│  ✗ wake_up/sleep                         │    │  ✓ AgentLoopWorker (Ray Actors)        │
│                                          │    │  ✓ AsyncLLMServerManager               │
│                                          │    │  ✓ RolloutReplica (vLLM/SGLang)        │
│                                          │    │  ✓ wake_up/sleep lifecycle             │
└──────────────────────────────────────────┘    └────────────────────────────────────────┘
```

### 2.4 Key Changes Summary

| Component | verl 0.5.x | verl 0.6.1 |
|-----------|------------|------------|
| **Batch Orchestration** | Direct agent calls | `AgentLoopManager` splits & coordinates |
| **Worker Parallelism** | None | `AgentLoopWorker` (Ray Actors) |
| **Agent Logic** | `ToolAgent` (LangGraph) | `AgentLoop` → `AgentLoopBase` subclasses |
| **Load Balancer** | None (single engine) | `AsyncLLMServerManager` |
| **Engine Wrapper** | `AsyncvLLMServerRegular` | `RolloutReplica` (abstract) |
| **vLLM Support** | `AsyncvLLMServerRegular` | `vLLMReplica` |
| **SGLang Support** | ✗ Not available | ✓ `SGLangReplica` |
| **Multi-Engine** | Single instance | Multiple replicas with routing |
| **Lifecycle** | Manual | `init_hybrid()`, `wake_up()`, `sleep()` |

---

## 3. Dispatcher vs verl's AgentLoop

### 3.1 The Design Decision

When integrating SkyRL-Agent with verl 0.6.1, we had two options:

| Option | Description |
|--------|-------------|
| **A. Use verl's AgentLoopManager** | Adopt verl's Ray-based agent parallelism with AgentLoopWorker |
| **B. Use SkyRL's Dispatcher** | Keep SkyRL's asyncio-based parallelism with custom dispatcher |

**We chose Option B (Dispatcher)**. Here's why:

### 3.2 Architecture Comparison

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              OPTION A: verl's AgentLoopManager (NOT USED)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         AgentLoopManager                                │ │
│  │                               │                                         │ │
│  │            ┌──────────────────┼──────────────────┐                     │ │
│  │            ▼                  ▼                  ▼                     │ │
│  │  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐       │ │
│  │  │ AgentLoopWorker  │ │ AgentLoopWorker  │ │ AgentLoopWorker  │       │ │
│  │  │   (Ray Actor)    │ │   (Ray Actor)    │ │   (Ray Actor)    │       │ │
│  │  │ ┌──────────────┐ │ │ ┌──────────────┐ │ │ ┌──────────────┐ │       │ │
│  │  │ │  AgentLoop   │ │ │ │  AgentLoop   │ │ │ │  AgentLoop   │ │       │ │
│  │  │ │  (LangGraph) │ │ │ │  (LangGraph) │ │ │ │  (LangGraph) │ │       │ │
│  │  │ └──────────────┘ │ │ └──────────────┘ │ │ └──────────────┘ │       │ │
│  │  └──────────────────┘ └──────────────────┘ └──────────────────┘       │ │
│  │            │                  │                  │                     │ │
│  │            └──────────────────┼──────────────────┘                     │ │
│  │                               ▼                                         │ │
│  │                    ┌──────────────────────┐                             │ │
│  │                    │ AsyncLLMServerManager│                             │ │
│  │                    └──────────────────────┘                             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Characteristics:                                                            │
│  • Multi-process (each worker is a Ray Actor)                               │
│  • LangGraph-based agent logic                                              │
│  • num_workers controls parallelism and padding                             │
│  • Tool calls via LangGraph tool interface                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│              OPTION B: SkyRL's Dispatcher (CHOSEN)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                      SkyAgentLoopManager                                │ │
│  │                        (Single Process)                                 │ │
│  │                                                                          │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │                   AsyncLLMServerManager                           │  │ │
│  │  │                  (shared by all tasks)                            │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  │                                                                          │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │                     AndroidAgentRunner                            │  │ │
│  │  │                                                                    │  │ │
│  │  │   ┌────────────────────────────────────────────────────────────┐  │  │ │
│  │  │   │           Dispatcher (async_fix_pool_retry)                │  │  │ │
│  │  │   │                                                            │  │  │ │
│  │  │   │   work_queue ──► worker ──► init ──► run ──► eval         │  │  │ │
│  │  │   │                                                            │  │  │ │
│  │  │   │   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │  │  │ │
│  │  │   │   │Container│ │Container│ │Container│ │Container│        │  │  │ │
│  │  │   │   │ Pool[0] │ │ Pool[1] │ │ Pool[2] │ │ Pool[3] │        │  │  │ │
│  │  │   │   │(Android)│ │(Android)│ │(Android)│ │(Android)│        │  │  │ │
│  │  │   │   └─────────┘ └─────────┘ └─────────┘ └─────────┘        │  │  │ │
│  │  │   └────────────────────────────────────────────────────────────┘  │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Characteristics:                                                            │
│  • Single-process with asyncio (coroutine-based)                            │
│  • Custom AndroidAgent logic                                                 │
│  • Container pool controls parallelism                                       │
│  • Centralized environment management (ContainerManager)                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Why Dispatcher Over verl's AgentLoop?

| Criterion | verl's AgentLoop | SkyRL's Dispatcher | Winner |
|-----------|------------------|-------------------|--------|
| **Android Environment** | Would need custom LangGraph integration | Native ContainerManager support | Dispatcher |
| **Process Overhead** | Ray Actor per worker | Single process, async coroutines | Dispatcher |
| **Agent Customization** | LangGraph-based workflows | Fully custom AndroidAgent | Dispatcher |
| **Error Recovery** | Basic exception handling | Built-in retry + container switching | Dispatcher |
| **Batching Control** | `num_workers` padding | `instance_id` deduplication | Dispatcher |
| **Code Coupling** | Tight with verl internals | Loose, only uses verl's ServerManager | Dispatcher |

### 3.4 Key Insight: Separation of Concerns

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SkyRL-Agent + verl 0.6.1 Integration                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        verl Responsibilities                         │   │
│  │  • PPO/GRPO training loop                                            │   │
│  │  • Weight updates (FSDP)                                             │   │
│  │  • RolloutReplica lifecycle (init, wake_up, sleep)                   │   │
│  │  • AsyncLLMServerManager (load balancing)                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                        │
│                                     │ generate() API                         │
│                                     ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     SkyRL-Agent Responsibilities                     │   │
│  │  • Agent logic (AndroidAgent)                                        │   │
│  │  • Environment management (ContainerManager)                         │   │
│  │  • Trajectory execution (Dispatcher)                                 │   │
│  │  • Error recovery (retry, container switching)                       │   │
│  │  • Tool execution (adb, search, etc.)                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Integration Point: SkyAgentLoopManager                                     │
│  • Bridges verl's RolloutReplica with SkyRL's Dispatcher                   │
│  • Uses AsyncLLMServerManager for LLM inference                            │
│  • Does NOT use verl's AgentLoopWorker                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.5 SkyRL Dispatcher Types

```python
# skyrl_agent/dispatcher/dispatchers.py

DISPATCHER_REGISTRY = {
    # Producer-consumer pipelining for init/run/eval phases
    "async_pipeline": async_pipeline_dispatcher,
    
    # Simple batch parallelism (all tasks start together)
    "async_batch": async_batch_dispatcher,
    
    # Fixed environment pool with work queue
    "async_fix_pool": async_fix_pool_dispatcher,
    
    # Fixed pool + retry logic + container switching (DEFAULT)
    "async_fix_pool_retry": async_fix_pool_retry_dispatcher,
}
```

---

## 4. Migration Summary

### 4.1 API Changes

| verl 0.5.x | verl 0.6.1 |
|------------|------------|
| `AsyncvLLMServerRegular` | `vLLMReplica` (via `get_rollout_replica_class`) |
| Direct server management | `RolloutReplica.init_hybrid()` / `init_standalone()` |
| N/A | `AsyncLLMServerManager` for load balancing |
| N/A | `wake_up()` / `sleep()` for colocate mode |
| N/A | `AgentLoopWorker` + `AgentLoopManager` |

### 4.2 Key Files Changed

| File | Change |
|------|--------|
| `verl_async_manager.py` | Use `RolloutReplica` + `AsyncLLMServerManager` instead of `AsyncvLLMServerRegular` |
| `pyproject.toml` | Update verl version to 0.6.1 |

### 4.3 Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GPU Sharing | Colocate | Simpler setup, verl 0.6.1 default |
| Agent Parallelism | Dispatcher | Android-specific needs, better error handling |
| verl's AgentLoopWorker | NOT USED | SkyRL has custom agent/env management |

### 4.4 Final Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                  SkyRL-Agent + verl 0.6.1 Final Architecture                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                      SkyAgentPPOTrainer (verl)                         │ │
│  │                      - PPO/GRPO training loop                           │ │
│  └─────────────────────────────────┬──────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    SkyAgentLoopManager (bridge)                         │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │ AsyncLLMServerManager ──► [vLLMReplica] [vLLMReplica] ...        │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │ AndroidAgentRunner ──► Dispatcher ──► [Containers...]            │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Key: SkyRL replaces verl's AgentLoop but uses verl's infrastructure       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```
