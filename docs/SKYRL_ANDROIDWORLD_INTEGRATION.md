# SkyRL-AndroidWorld Integration Tutorial

## 1. Introduction

This document explains how the SkyRL-Agent framework is extended to support AndroidWorld, a benchmark for GUI agents on Android devices.

### How SkyRL-Agent Extends to AndroidWorld

The AndroidWorld integration follows the three-layer architecture defined in the SkyRL-Agent framework. Each layer has specific implementations:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SkyRL-Agent Framework                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Base Classes                      AndroidWorld Implementations            │
│   ────────────                      ──────────────────────────              │
│                                                                             │
│   ┌─────────────────┐               ┌─────────────────────────┐             │
│   │  AgentRunner    │ ──extends──▶  │  AndroidAgentRunner     │             │
│   └─────────────────┘               └─────────────────────────┘             │
│                                                                             │
│   ┌─────────────────┐               ┌─────────────────────────┐             │
│   │  BaseTrajectory │ ──extends──▶  │  AndroidTrajectory      │             │
│   └─────────────────┘               └─────────────────────────┘             │
│                                                                             │
│   ┌─────────────────┐               ┌─────────────────────────┐             │
│   │  BaseTask       │ ──extends──▶  │  AndroidTask            │             │
│   └─────────────────┘               └─────────────────────────┘             │
│                                                                             │
│   ┌─────────────────┐               ┌─────────────────────────┐             │
│   │  BaseTool       │ ──extends──▶  │  AndroidEnvTool         │             │
│   └─────────────────┘               └─────────────────────────┘             │
│                                                                             │
│   New Components (AndroidWorld-specific):                                   │
│   ─────────────────────────────────────────                                 │
│   ┌─────────────────────────────────────────────────────────────┐           │
│   │  AndroidAgent      │  ContainerManager  │  RuntimeClient    │           │
│   └─────────────────────────────────────────────────────────────┘           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Repository Structure

```
skyrl-agent/
├── skyrl_agent/
│   ├── agents/
│   │   ├── base.py                    # Base classes: AgentRunner, BaseTrajectory
│   │   └── android/
│   │       ├── android_agent.py       # AndroidAgent (VLM-based GUI agent)
│   │       ├── android_runner.py      # AndroidAgentRunner
│   │       ├── android_trajectory.py  # AndroidTrajectory
│   │       └── utils.py               # Message/image/action utilities
│   │
│   ├── tasks/
│   │   ├── base.py                    # BaseTask
│   │   └── android/
│   │       └── android_task.py        # AndroidTask
│   │
│   ├── tools/
│   │   ├── base.py                    # BaseTool, ToolRegistry
│   │   ├── android_env.py             # AndroidEnvTool (actions)
│   │   └── search_engine.py           # SearchEngineTool
│   │
│   ├── runtime/
│   │   └── android/
│   │       ├── container_manager.py   # Docker container pool management
│   │       └── runtime_client.py      # HTTP client for container communication
│   │
│   └── integrations/
│       └── verl/
│           └── android_dataset.py     # Dataset loader for AndroidWorld tasks
│
├── examples/
│   └── run_verl/
│       ├── verl_android.yaml          # Training configuration
│       ├── verl_android.sh            # Training launcher script
│       ├── verl_android_inference.yaml # Inference configuration
│       └── verl_android_inference.sh  # Inference launcher script
│
└── data/
    └── androidworld_generalization/   # Task dataset files (JSONL)
```

---

## 2. Architecture Overview

### High-Level Integration Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Backend Layer                                  │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         VERL Trainer                                  │  │
│  │  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────────┐   │  │
│  │  │ PPO/GRPO    │◀──▶│ SkyAgentLoop     │◀──▶│ AsyncLLMServer      │   │  │
│  │  │ Training    │    │ Manager          │    │ Manager             │   │  │
│  │  └─────────────┘    └──────────────────┘    └─────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼ VeRLBackend                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                               Agent Layer                                   │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      AndroidAgentRunner                               │  │
│  │  ┌──────────────────┐    ┌──────────────────┐    ┌────────────────┐   │  │
│  │  │ AndroidTrajectory│    │ AndroidTrajectory│    │ Dispatcher     │   │  │
│  │  │ (traj_0)         │    │ (traj_1)         │    │ (async_fix_    │   │  │
│  │  │ ┌──────────────┐ │    │ ┌──────────────┐ │    │  pool)         │   │  │
│  │  │ │AndroidAgent  │ │    │ │AndroidAgent  │ │    └────────────────┘   │  │
│  │  │ │(VLM-based)   │ │    │ │(VLM-based)   │ │                         │  │
│  │  │ └──────────────┘ │    │ └──────────────┘ │                         │  │
│  │  └──────────────────┘    └──────────────────┘                         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼ RuntimeClient                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                            Environment Layer                                │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                          AndroidTask                                  │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │                    ContainerManager                             │  │  │
│  │  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐     │  │  │
│  │  │  │ Container │  │ Container │  │ Container │  │ Container │     │  │  │
│  │  │  │ (env_0)   │  │ (env_1)   │  │ (env_2)   │  │ (env_3)   │     │  │  │
│  │  │  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │     │  │  │
│  │  │  │ │Android│ │  │ │Android│ │  │ │Android│ │  │ │Android│ │     │  │  │
│  │  │  │ │Emulat.│ │  │ │Emulat.│ │  │ │Emulat.│ │  │ │Emulat.│ │     │  │  │
│  │  │  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │     │  │  │
│  │  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘     │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Components

### 3.1 Android Agent Layer

#### AndroidAgent

The `AndroidAgent` is a Vision-Language Model (VLM) based GUI agent that interacts with Android devices through screenshots and actions.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AndroidAgent                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Input:                                                                    │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  instruction: List[Dict]     # Task instruction messages            │   │
│   │  observation: screenshot     # Current Android screen (image)       │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Core Loop (run → step):                                                   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │   │
│   │   │ prepare_     │────▶│ LLM Generate │────▶│ parse_uitars │        │   │
│   │   │ input_ids()  │     │ (via backend)│     │ _action()    │        │   │
│   │   └──────────────┘     └──────────────┘     └──────────────┘        │   │
│   │          │                                          │               │   │
│   │          │                                          ▼               │   │
│   │   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │   │
│   │   │ accumulate_  │◀────│ process_for_ │◀────│ execute      │        │   │
│   │   │ tensors()    │     │ training()   │     │ action       │        │   │
│   │   └──────────────┘     └──────────────┘     └──────────────┘        │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Output (TrajectoryState):                                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  - instance_id, trajectory_id                                       │   │
│   │  - messages: List[Dict]        # Conversation history               │   │
│   │  - images: List[np.ndarray]    # Screenshots                        │   │
│   │  - input_ids, labels           # Training tensors                   │   │
│   │  - pixel_values, image_grid_thw # VLM vision tensors                │   │
│   │  - finish_reason, reward       # Result metrics                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Features:**
- Uses UITARS action format: `Thought: <reasoning>\nAction: <action_call>`
- Processes screenshots as vision tokens via VLM processor
- Incrementally accumulates training tensors during generation
- Supports Qwen2-VL architecture with image grid handling

**Action Format Examples:**
```python
# Click action
"Thought: I need to click the Settings icon\nAction: click(start_box='<|box_start|>(540,960)<|box_end|>')"

# Type action
"Thought: I need to enter the search query\nAction: type(content='weather today')"

# Scroll action
"Thought: I need to scroll down to see more\nAction: scroll(start_box='<|box_start|>(540,800)<|box_end|>', end_box='<|box_start|>(540,400)<|box_end|>')"

# Complete action
"Thought: Task is complete\nAction: finished(content='')"
```

#### AndroidTrajectory

Orchestrates the trajectory lifecycle by coordinating agent, environment, and evaluation.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AndroidTrajectory                                 │
│                         (extends BaseTrajectory)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Lifecycle Methods:                                                        │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  initialize_trajectory()                                            │   │
│   │  ─────────────────────────                                          │   │
│   │  1. Allocate container from ContainerManager                        │   │
│   │  2. Create RuntimeClient (env_handle)                               │   │
│   │  3. Send reset() to environment                                     │   │
│   │  4. Receive initial observation (screenshot)                        │   │
│   │  5. Build instruction messages                                      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                           │                                                 │
│                           ▼                                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  generate_trajectory()                                              │   │
│   │  ────────────────────────                                           │   │
│   │  1. Create AndroidAgent with env_handle                             │   │
│   │  2. Run agent loop (agent.run())                                    │   │
│   │  3. Retrieve TrajectoryState from agent                             │   │
│   │  4. Store result for evaluation                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                           │                                                 │
│                           ▼                                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  evaluate_trajectory()                                              │   │
│   │  ──────────────────────                                             │   │
│   │  1. Call AndroidTask.evaluate_result()                              │   │
│   │  2. Compute reward based on task completion                         │   │
│   │  3. Return final result dict                                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### AndroidAgentRunner

Manages multiple trajectories using the dispatcher pattern.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AndroidAgentRunner                                 │
│                          (extends AgentRunner)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Initialization:                                                           │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  - Load VLM processor from model path                               │   │
│   │  - Initialize environment pool (once, reused across batches)        │   │
│   │  - Configure dispatcher (async_fix_pool)                            │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   run(input_batch, val_mode):                                               │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   Input Batch                                                       │   │
│   │   ┌─────────────────────────────────────────────────────────┐       │   │
│   │   │ instance_0  │  instance_1  │  instance_2  │  instance_3 │       │   │
│   │   └─────────────────────────────────────────────────────────┘       │   │
│   │              │                                                      │   │
│   │              ▼                                                      │   │
│   │   ┌─────────────────────────────────────────────────────────┐       │   │
│   │   │              _initialize_trajectories()                 │       │   │
│   │   │  Creates AndroidTrajectory for each instance            │       │   │
│   │   └─────────────────────────────────────────────────────────┘       │   │
│   │              │                                                      │   │
│   │              ▼                                                      │   │
│   │   ┌─────────────────────────────────────────────────────────┐       │   │
│   │   │              Dispatcher (async_fix_pool)                │       │   │
│   │   │  Executes trajectories in parallel with env pool        │       │   │
│   │   └─────────────────────────────────────────────────────────┘       │   │
│   │              │                                                      │   │
│   │              ▼                                                      │   │
│   │   ┌─────────────────────────────────────────────────────────┐       │   │
│   │   │              _post_process_results()                    │       │   │
│   │   │  - Extract VLM tensors from agent states                │       │   │
│   │   │  - Compute rollout metrics (success rate, avg turns)    │       │   │
│   │   │  - Format output for training backend                   │       │   │
│   │   └─────────────────────────────────────────────────────────┘       │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Android Environment Layer (Runtime)

#### AndroidTask

Static class providing task interface methods for AndroidWorld.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AndroidTask                                    │
│                            (extends BaseTask)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   CALLED ONCE (Before/After All Trajectories)                               │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  initialize_runtime(env_config) → ContainerManager                  │   │
│   │  ───────────────────────────────────────────────                    │   │
│   │  Called: ONCE at startup (before any trajectory)                    │   │
│   │  - Creates Docker container pool                                    │   │
│   │  - Starts Android emulators in each container                       │   │
│   │  - Returns ContainerManager for allocation                          │   │
│   │  - Pool is reused across all batches/epochs                         │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  cleanup_runtime()                                                  │   │
│   │  ────────────────────                                               │   │
│   │  Called: ONCE at shutdown (after all trajectories complete)         │   │
│   │  - Stops all Docker containers                                      │   │
│   │  - Releases allocated resources                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   CALLED PER TRAJECTORY                                                     │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  get_instruction(instance) → List[Dict]                             │   │
│   │  ─────────────────────────────────────                              │   │
│   │  Called: Once per trajectory (during initialize_trajectory)         │   │
│   │  - Builds instruction messages from task instance                   │   │
│   │  - Returns formatted user message with task description             │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  format_observation(observation) → List[Dict]                       │   │
│   │  ────────────────────────────────────────────                       │   │
│   │  Called: Multiple times per trajectory (each step)                  │   │
│   │  - Converts screenshot to message format                            │   │
│   │  - Returns user message with image content                          │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  evaluate_result(result, instance, ...) → Dict                      │   │
│   │  ─────────────────────────────────────────────                      │   │
│   │  Called: Once per trajectory (during evaluate_trajectory)           │   │
│   │  - Evaluates trajectory result                                      │   │
│   │  - Computes reward based on task completion                         │   │
│   │  - Returns evaluation metrics                                       │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  complete_runtime(env_handle) → None                                │   │
│   │  ───────────────────────────────────                                │   │
│   │  Called: Once per trajectory (after trajectory completes)           │   │
│   │  - Optional cleanup for individual trajectory                       │   │
│   │  - Releases container back to pool                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   LIFECYCLE DIAGRAM                                                         │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   Training Start                                                            │
│        │                                                                    │
│        ▼                                                                    │
│   ┌────────────────────────┐                                                │
│   │  initialize_runtime()  │  ◀── Called ONCE                               │
│   └────────────────────────┘                                                │
│        │                                                                    │
│        ▼                                                                    │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │  For each batch of trajectories:                                   │    │
│   │  ┌──────────────────────────────────────────────────────────────┐  │    │
│   │  │  For each trajectory:                                        │  │    │
│   │  │    ├─▶ get_instruction()      ◀── Per trajectory             │  │    │
│   │  │    ├─▶ format_observation()   ◀── Multiple times per traj    │  │    │
│   │  │    │      ... (agent steps)                                  │  │    │
│   │  │    ├─▶ evaluate_result()      ◀── Per trajectory             │  │    │
│   │  │    └─▶ complete_runtime()     ◀── Per trajectory             │  │    │
│   │  └──────────────────────────────────────────────────────────────┘  │    │
│   └────────────────────────────────────────────────────────────────────┘    │
│        │                                                                    │
│        ▼                                                                    │
│   ┌────────────────────────┐                                                │
│   │   cleanup_runtime()    │  ◀── Called ONCE                               │
│   └────────────────────────┘                                                │
│        │                                                                    │
│        ▼                                                                    │
│   Training End                                                              │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   CONFIGURATION                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  pool_size: 8              # Number of parallel containers          │   │
│   │  docker_image: "androidworld:full_adb_agent"                                    │   │
│   │  snapshot: "clean"         # Emulator snapshot to load              │   │
│   │  sample_mode: "sequential" # Task sampling strategy                 │   │
│   │  train_task_family: "android_world"                                 │   │
│   │  val_task_family: "android_world"                                   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### ContainerManager

Manages a pool of Docker containers, each running an Android emulator.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ContainerManager                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Container Pool Architecture:                                              │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐               │   │
│   │   │ Container 0 │   │ Container 1 │   │ Container 2 │   ...         │   │
│   │   │ ┌─────────┐ │   │ ┌─────────┐ │   │ ┌─────────┐ │               │   │
│   │   │ │ Android │ │   │ │ Android │ │   │ │ Android │ │               │   │
│   │   │ │ Emulator│ │   │ │ Emulator│ │   │ │ Emulator│ │               │   │
│   │   │ └─────────┘ │   │ └─────────┘ │   │ └─────────┘ │               │   │
│   │   │             │   │             │   │             │               │   │
│   │   │ Ports:      │   │ Ports:      │   │ Ports:      │               │   │
│   │   │ - server    │   │ - server    │   │ - server    │               │   │
│   │   │ - emulator  │   │ - emulator  │   │ - emulator  │               │   │
│   │   │ - grpc      │   │ - grpc      │   │ - grpc      │               │   │
│   │   │             │   │             │   │             │               │   │
│   │   │ State:      │   │ State:      │   │ State:      │               │   │
│   │   │ [ready]     │   │ [in_use]    │   │ [ready]     │               │   │
│   │   └─────────────┘   └─────────────┘   └─────────────┘               │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Key Methods:                                                              │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  create_pool(pool_size, ...) → List[ContainerInstance]              │   │
│   │  ─────────────────────────────────────────────────────              │   │
│   │  - Allocates ports for each container                               │   │
│   │  - Starts Docker containers with Android emulators                  │   │
│   │  - Waits for containers to become healthy                           │   │
│   │  - Returns list of container instances                              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  allocate_container(batch_idx, trajectory_id) → ContainerInstance   │   │
│   │  ───────────────────────────────────────────────────────────────    │   │
│   │  - Finds available container (state == "ready")                     │   │
│   │  - Marks container as "in_use"                                      │   │
│   │  - Associates trajectory with container                             │   │
│   │  - Returns container instance                                       │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  release_container(container, success, error)                       │   │
│   │  ────────────────────────────────────────────                       │   │
│   │  - Marks container as "ready" for reuse                             │   │
│   │  - Tracks failed trajectories if error occurred                     │   │
│   │  - Optionally restarts container if unhealthy                       │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Port Allocation:                                                          │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Container N:                                                       │   │
│   │  - server_port:   5000 + 2*N                                        │   │
│   │  - emulator_port: 5574 + 2*N                                        │   │
│   │  - grpc_port:     8574 + 2*N                                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Docker Container Internal Structure

Each Docker container runs a complete Android environment with a FastAPI server for external communication.

**Source:** `docker/android/server/`

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Docker Container Internal Structure                      │
│                         (docker/android/server)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                         Docker Container                            │   │
│   │                                                                     │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │              FastAPI Server (server.py)                     │   │   │
│   │   │                   Port: SERVER_PORT                         │   │   │
│   │   │                                                             │   │   │
│   │   │   REST Endpoints:                                           │   │   │
│   │   │   ┌───────────────────────────────────────────────────────┐ │   │   │
│   │   │   │ POST /reset  → Reset env, return initial observation  │ │   │   │
│   │   │   │ POST /step   → Execute action, return new state       │ │   │   │
│   │   │   │ GET  /health → Health check for container monitoring  │ │   │   │
│   │   │   │ POST /env_log → Log messages to task-specific file    │ │   │   │
│   │   │   └───────────────────────────────────────────────────────┘ │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                              │                                      │   │
│   │                              ▼                                      │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │            AndroidWorldEnv (env.py)                         │   │   │
│   │   │                                                             │   │   │
│   │   │   ┌───────────────────┐   ┌───────────────────────────────┐ │   │   │
│   │   │   │ Task Registry     │   │ State Management              │ │   │   │
│   │   │   │ - Load tasks      │   │ - Episode history             │ │   │   │
│   │   │   │ - Sample tasks    │   │ - Screenshot capture          │ │   │   │
│   │   │   │ - Success check   │   │ - UI tree extraction          │ │   │   │
│   │   │   └───────────────────┘   └───────────────────────────────┘ │   │   │
│   │   │                                                             │   │   │
│   │   │   Key Methods:                                              │   │   │
│   │   │   - reset(seed, options) → observation, info                │   │   │
│   │   │   - step(action) → observation, reward, terminated, info    │   │   │
│   │   │   - evaluation() → success/failure                          │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                              │                                      │   │
│   │                              ▼ ADB / gRPC                           │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │              Android Emulator (AVD)                         │   │   │
│   │   │                                                             │   │   │
│   │   │   ┌───────────────────────────────────────────────────────┐ │   │   │
│   │   │   │ AVD: AWAvd                                            │ │   │   │
│   │   │   │ - Console Port: EMULATOR_PORT (5554)                  │ │   │   │
│   │   │   │ - gRPC Port: GRPC_PORT (8554)                         │ │   │   │
│   │   │   │ - Mode: Headless (-no-window)                         │ │   │   │
│   │   │   │ - Snapshot: Configurable (default: "clean")           │ │   │   │
│   │   │   └───────────────────────────────────────────────────────┘ │   │   │
│   │   │                                                             │   │   │
│   │   │   Capabilities:                                             │   │   │
│   │   │   - Touch input (tap, swipe, long press)                    │   │   │
│   │   │   - Text input (keyboard simulation)                        │   │   │
│   │   │   - Navigation (home, back buttons)                         │   │   │
│   │   │   - App launching                                           │   │   │
│   │   │   - Screenshot capture                                      │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                                                                     │   │
│   │   Data Storage:                                                     │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │ /data/images/     → Screenshot storage                      │   │   │
│   │   │ /data/log/        → Server and task logs                    │   │   │
│   │   │   ├── server_logs/env{id}.log                               │   │   │
│   │   │   └── {mode}/epoch{N}/task{id}/                             │   │   │
│   │   │       ├── log.log                                           │   │   │
│   │   │       ├── {step}.png                                        │   │   │
│   │   │       └── {step}_ui_element.json                            │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Environment Variables:                                                    │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  SERVER_PORT     = 5000      # FastAPI server port                  │   │
│   │  ENV_ID          = 0         # Environment instance ID              │   │
│   │  ENV_SAMPLE_MODE = random    # Task sampling ("random"/"sequential")│   │
│   │  ENV_SNAPSHOT    = clean     # Emulator snapshot to load            │   │
│   │  ENV_TASK_FAMILY = android   # Task family filter                   │   │
│   │  EMULATOR_PORT   = 5554      # Android emulator console port        │   │
│   │  GRPC_PORT       = 8554      # Android emulator gRPC port           │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Request/Response Flow:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Request/Response Flow                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   RuntimeClient                    Docker Container                         │
│   (skyrl-agent)                    (docker/android/server)                  │
│                                                                             │
│   ┌─────────────┐                  ┌─────────────────────────────────────┐  │
│   │             │  POST /reset     │                                     │  │
│   │             │ ───────────────▶ │  FastAPI receives request           │  │
│   │             │  {task_id,       │         │                           │  │
│   │             │   seed,          │         ▼                           │  │
│   │             │   task_family}   │  AndroidWorldEnv.reset()            │  │
│   │             │                  │         │                           │  │
│   │             │                  │         ▼                           │  │
│   │             │                  │  Load task from registry            │  │
│   │             │                  │  Restore emulator snapshot          │  │
│   │             │                  │  Capture initial screenshot         │  │
│   │             │                  │         │                           │  │
│   │             │  {observation,   │         │                           │  │
│   │             │   info}          │ ◀───────┘                           │  │
│   │             │ ◀─────────────── │                                     │  │
│   │             │                  │                                     │  │
│   │             │  POST /step      │                                     │  │
│   │             │ ───────────────▶ │  FastAPI receives action            │  │
│   │             │  {action_type,   │         │                           │  │
│   │             │   coordinate,    │         ▼                           │  │
│   │             │   text, ...}     │  AndroidWorldEnv.step()             │  │
│   │             │                  │         │                           │  │
│   │             │                  │         ▼                           │  │
│   │             │                  │  Execute action on emulator         │  │
│   │             │                  │  (ADB touch/type/swipe)             │  │
│   │             │                  │         │                           │  │
│   │             │                  │         ▼                           │  │
│   │             │                  │  Capture new screenshot             │  │
│   │             │                  │  Check task success                 │  │
│   │             │                  │         │                           │  │
│   │             │  {observation,   │         │                           │  │
│   │             │   reward,        │ ◀───────┘                           │  │
│   │             │   terminated,    │                                     │  │
│   │             │   truncated,     │                                     │  │
│   │             │   info}          │                                     │  │
│   │             │ ◀─────────────── │                                     │  │
│   └─────────────┘                  └─────────────────────────────────────┘  │
│                                                                             │
│   Observation Format:                                                       │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  {                                                                  │   │
│   │    "pixels": "<base64-encoded-image>",                              │   │
│   │    "image_shape": [H, W, 3],                                        │   │
│   │    "image_dtype": "uint8"                                           │   │
│   │  }                                                                  │   │
│   │                                                                     │   │
│   │  Client decodes:                                                    │   │
│   │  np.frombuffer(base64.b64decode(pixels), dtype).reshape(shape)      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### RuntimeClient

HTTP client for communicating with Android environment containers.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             RuntimeClient                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Interface (same as AndroidWorldHostEnv):                                  │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  reset(payload) → (observation, info)                               │   │
│   │  ────────────────────────────────────                               │   │
│   │  payload: {                                                         │   │
│   │    "task_id": int,                                                  │   │
│   │    "seed": int,                                                     │   │
│   │    "task_family": str                                               │   │
│   │  }                                                                  │   │
│   │  observation: {                                                     │   │
│   │    "pixels": np.ndarray  # Screenshot (H, W, 3)                     │   │
│   │  }                                                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  step(payload) → (observation, reward, terminated, truncated, info) │   │
│   │  ──────────────────────────────────────────────────────────────     │   │
│   │  payload: {                                                         │   │
│   │    "action_type": "click" | "type" | "scroll" | ...,                │   │
│   │    "coordinate": [x, y],  # for click/scroll                        │   │
│   │    "text": str,           # for type action                         │   │
│   │    ...                                                              │   │
│   │  }                                                                  │   │
│   │  observation: {                                                     │   │
│   │    "pixels": np.ndarray  # New screenshot after action              │   │
│   │  }                                                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  is_healthy() → bool                                                │   │
│   │  ──────────────────                                                 │   │
│   │  - Checks container health via HTTP /health endpoint                │   │
│   │  - Returns True if container is responsive                          │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Communication:                                                            │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  RuntimeClient ─────HTTP/REST────▶ Container Server                 │   │
│   │                                          │                          │   │
│   │                                          ▼                          │   │
│   │                                    Android Emulator                 │   │
│   │                                    (via ADB commands)               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Component Cardinality & Relationships

This diagram clarifies the cardinality (how many instances) of each component and their relationships.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│            Component Cardinality: ContainerManager vs RuntimeClient         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   KEY RELATIONSHIPS                                                         │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Component          │  Cardinality   │  Lifecycle                   │   │
│   ├─────────────────────┼────────────────┼──────────────────────────────┤   │
│   │  ContainerManager   │  1 (singleton) │  Entire training run         │   │
│   │  Container (pool)   │  N (pool_size) │  Reused across trajectories  │   │
│   │  RuntimeClient      │  Per trajectory│  Created/destroyed per traj  │   │
│   │  AndroidAgent       │  Per trajectory│  Created/destroyed per traj  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   ARCHITECTURE DIAGRAM                                                      │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│                        ┌─────────────────────────────────────┐              │
│                        │         AndroidAgentRunner          │              │
│                        │            (1 instance)             │              │
│                        └─────────────────┬───────────────────┘              │
│                                          │                                  │
│                                          │ manages                          │
│                                          ▼                                  │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                    Multiple AndroidTrajectory Instances              │  │
│   │  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐            │  │
│   │  │ Trajectory 0   │ │ Trajectory 1   │ │ Trajectory 2   │  ...       │  │
│   │  │ ┌────────────┐ │ │ ┌────────────┐ │ │ ┌────────────┐ │            │  │
│   │  │ │AndroidAgent│ │ │ │AndroidAgent│ │ │ │AndroidAgent│ │            │  │
│   │  │ └────────────┘ │ │ └────────────┘ │ │ └────────────┘ │            │  │
│   │  │ ┌────────────┐ │ │ ┌────────────┐ │ │ ┌────────────┐ │            │  │
│   │  │ │RuntimeClient│ │ │RuntimeClient│ │ │RuntimeClient│ │  ◀── 1 per │  │
│   │  │ └──────┬─────┘ │ │ └──────┬─────┘ │ │ └──────┬─────┘ │   trajectory│  │
│   │  └────────┼───────┘ └────────┼───────┘ └────────┼───────┘            │  │
│   └───────────┼──────────────────┼──────────────────┼────────────────────┘  │
│               │                  │                  │                       │
│               │ HTTP             │ HTTP             │ HTTP                  │
│               ▼                  ▼                  ▼                       │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │              ContainerManager (1 SINGLETON for entire system)        │  │
│   │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│   │  │                     Container Pool (N containers)               │ │  │
│   │  │  ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐  │ │  │
│   │  │  │Container 0│   │Container 1│   │Container 2│   │Container 3│  │ │  │
│   │  │  │ [in_use]  │   │ [in_use]  │   │ [in_use]  │   │  [ready]  │  │ │  │
│   │  │  │     ▲     │   │     ▲     │   │     ▲     │   │           │  │ │  │
│   │  │  │  traj_0   │   │  traj_1   │   │  traj_2   │   │ available │  │ │  │
│   │  │  └───────────┘   └───────────┘   └───────────┘   └───────────┘  │ │  │
│   │  └─────────────────────────────────────────────────────────────────┘ │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   LIFECYCLE FLOW                                                            │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   Training Start                                                            │
│        │                                                                    │
│        ▼                                                                    │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │  ContainerManager.create_pool(pool_size=4)                         │    │
│   │  ════════════════════════════════════════                          │    │
│   │  Creates 4 containers, ALL marked as [ready]                       │    │
│   │  This happens ONCE at startup                                      │    │
│   └────────────────────────────────────────────────────────────────────┘    │
│        │                                                                    │
│        ▼                                                                    │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │  For each trajectory (e.g., 8 trajectories, 4 containers):         │    │
│   │                                                                    │    │
│   │  ┌──────────────────────────────────────────────────────────────┐  │    │
│   │  │  initialize_trajectory():                                    │  │    │
│   │  │    1. container = ContainerManager.allocate_container()      │  │    │
│   │  │       └─▶ Finds [ready] container, marks it as [in_use]      │  │    │
│   │  │    2. runtime_client = RuntimeClient(container.server_port)  │  │    │
│   │  │       └─▶ Creates NEW RuntimeClient for THIS trajectory      │  │    │
│   │  │    3. runtime_client.reset(task_info)                        │  │    │
│   │  │       └─▶ HTTP POST to container's FastAPI server            │  │    │
│   │  └──────────────────────────────────────────────────────────────┘  │    │
│   │                              │                                     │    │
│   │                              ▼                                     │    │
│   │  ┌──────────────────────────────────────────────────────────────┐  │    │
│   │  │  generate_trajectory():                                      │  │    │
│   │  │    - Agent uses runtime_client for step() calls              │  │    │
│   │  │    - Each step: screenshot → VLM → action → execute          │  │    │
│   │  └──────────────────────────────────────────────────────────────┘  │    │
│   │                              │                                     │    │
│   │                              ▼                                     │    │
│   │  ┌──────────────────────────────────────────────────────────────┐  │    │
│   │  │  After trajectory completes:                                 │  │    │
│   │  │    1. ContainerManager.release_container(container)          │  │    │
│   │  │       └─▶ Marks container as [ready] for reuse               │  │    │
│   │  │    2. RuntimeClient is discarded (garbage collected)         │  │    │
│   │  │       └─▶ Next trajectory creates its OWN RuntimeClient      │  │    │
│   │  └──────────────────────────────────────────────────────────────┘  │    │
│   │                                                                    │    │
│   └────────────────────────────────────────────────────────────────────┘    │
│        │                                                                    │
│        ▼                                                                    │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │  Training End                                                      │    │
│   │  ════════════                                                      │    │
│   │  ContainerManager.cleanup() - stops all containers ONCE            │    │
│   └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   EXAMPLE: 8 Trajectories with 4 Containers                                 │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   Time ──────────────────────────────────────────────────────────────────▶  │
│                                                                             │
│   Container 0: │ traj_0 (RC_0) █████████│ traj_4 (RC_4) ███████│            │
│   Container 1: │ traj_1 (RC_1) ███████████│ traj_5 (RC_5) █████│            │
│   Container 2: │ traj_2 (RC_2) ███████│ traj_6 (RC_6) █████████████│        │
│   Container 3: │ traj_3 (RC_3) █████████████│ traj_7 (RC_7) ███│            │
│                                                                             │
│   Legend:                                                                   │
│   - RC_N = RuntimeClient instance N (each trajectory gets its own)          │
│   - Container is REUSED, RuntimeClient is CREATED FRESH each time           │
│   - traj_0 and traj_4 share Container 0, but have DIFFERENT RuntimeClients  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### ContainerManager vs Dispatcher

These two components operate at **different layers** and have distinct responsibilities:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ContainerManager vs Dispatcher                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   COMPARISON TABLE                                                          │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Aspect          │  ContainerManager      │  Dispatcher             │   │
│   ├───────────────────┼────────────────────────┼─────────────────────────┤   │
│   │  Layer           │  Infrastructure        │  Execution/Orchesttic   │   │
│   │  What it manages │  Docker containers     │  Work distribution      │   │
│   │  Lifecycle       │  Entire training run   │  Per run() call         │   │
│   │  Responsibility  │  Create, health-check, │  Distribute trajectories│   │
│   │                  │  restart containers    │  across available envs  │   │
│   │  Knows about     │  Docker, ports, health │  Trajectories, env IDs  │   │
│   │  Doesn't know    │  Trajectories, agents  │  Docker, containers     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   HOW THEY WORK TOGETHER                                                    │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   Training Start                                                            │
│        │                                                                    │
│        ▼                                                                    │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │  INFRASTRUCTURE LAYER (ContainerManager)                           │    │
│   │  ════════════════════════════════════════                          │    │
│   │  ContainerManager.create_pool(pool_size=4)                         │    │
│   │    → Creates 4 Docker containers                                   │    │
│   │    → Wraps each in RuntimeClient                                   │    │
│   │    → Returns: env_pool = [RC_0, RC_1, RC_2, RC_3]                  │    │
│   │                                                                    │    │
│   │  This happens ONCE, env_pool is stored persistently                │    │
│   └────────────────────────────────────────────────────────────────────┘    │
│        │                                                                    │
│        │  env_pool passed to dispatcher                                     │
│        ▼                                                                    │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │  EXECUTION LAYER (Dispatcher) - Called for EACH batch              │    │
│   │  ══════════════════════════════════════════════                    │    │
│   │                                                                    │    │
│   │  Dispatcher receives:                                              │    │
│   │    - env_pool: [RC_0, RC_1, RC_2, RC_3]  (4 RuntimeClients)       │    │
│   │    - work: 8 trajectories to execute                               │    │
│   │                                                                    │    │
│   │  Dispatcher creates two queues:                                    │    │
│   │    ┌─────────────────┐    ┌─────────────────────────────────────┐  │    │
│   │    │  env_queue      │    │  work_queue                         │  │    │
│   │    │  ─────────────  │    │  ───────────                        │  │    │
│   │    │  [0, 1, 2, 3]   │    │  [(0,0), (0,1), (1,0), (1,1), ...]  │  │    │
│   │    │  (available IDs)│    │  (batch_idx, trajectory_id pairs)   │  │    │
│   │    └─────────────────┘    └─────────────────────────────────────┘  │    │
│   │                                                                    │    │
│   │  Dispatcher launches 4 worker coroutines (one per env):           │    │
│   │    ┌─────────────────────────────────────────────────────────┐    │    │
│   │    │  Worker loop:                                           │    │    │
│   │    │    1. work_item = work_queue.get()   # Get trajectory   │    │    │
│   │    │    2. env_id = env_queue.get()       # Get available env│    │    │
│   │    │    3. Run: init_fn → run_fn → eval_fn                   │    │    │
│   │    │    4. env_queue.put(env_id)          # Release env      │    │    │
│   │    │    5. Repeat until work_queue empty                     │    │    │
│   │    └─────────────────────────────────────────────────────────┘    │    │
│   │                                                                    │    │
│   └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   KEY INSIGHT: SEPARATION OF CONCERNS                                       │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   ContainerManager: "I manage the PHYSICAL RESOURCES (Docker containers)"   │
│                     - Create containers, allocate ports                     │
│                     - Monitor health, restart if needed                     │
│                     - Long-lived, persistent across all batches             │
│                                                                             │
│   Dispatcher:       "I manage the WORK SCHEDULING (trajectory execution)"   │
│                     - Distribute work items across available envs           │
│                     - Call lifecycle functions (init, run, eval)            │
│                     - Short-lived, fresh for each run() call                │
│                                                                             │
│   They are DECOUPLED:                                                       │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │  ContainerManager ──creates──▶ RuntimeClient pool (env_pool)        │   │
│   │                                        │                            │   │
│   │                                        │ passed to                  │   │
│   │                                        ▼                            │   │
│   │  Dispatcher ─────uses env_pool to────▶ schedule trajectory exec     │   │
│   │                                                                     │   │
│   │  ContainerManager doesn't know about trajectories                   │   │
│   │  Dispatcher doesn't know about Docker                               │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   VISUAL: 8 Trajectories, 4 Containers, Dispatcher Scheduling              │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   work_queue: [(0,0), (0,1), (1,0), (1,1), (2,0), (2,1), (3,0), (3,1)]      │
│                  │      │      │      │      │      │      │      │        │
│                  ▼      │      │      │      │      │      │      │        │
│   Worker 0: ═══traj_0═══│══════│══════│═══traj_4═══│══════│══════│═══▶     │
│                         ▼      │      │            ▼      │      │         │
│   Worker 1: ═══════traj_1══════│══════│═══════traj_5══════│══════│═══▶     │
│                                ▼      │                   ▼      │         │
│   Worker 2: ═══════════traj_2═════════│═══════════traj_6═════════│═══▶     │
│                                       ▼                          ▼         │
│   Worker 3: ═══════════════traj_3═════════════════════traj_7═════════▶     │
│                                                                             │
│   Each worker:                                                              │
│     - Owns one env (RC_0, RC_1, RC_2, RC_3)                                │
│     - Pulls work items from shared work_queue                               │
│     - Processes trajectories sequentially on its assigned env               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Android Tools

#### AndroidEnvTool

Tool wrapper for executing actions in the Android environment.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             AndroidEnvTool                                  │
│                            (extends BaseTool)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Supported Actions:                                                        │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Touch Actions:                                                     │   │
│   │  - click(start_box)           # Tap at coordinates                  │   │
│   │  - long_press(start_box, time) # Long press                         │   │
│   │                                                                     │   │
│   │  Text Actions:                                                      │   │
│   │  - type(content)              # Enter text                          │   │
│   │  - input_text(content)        # Alias for type                      │   │
│   │                                                                     │   │
│   │  Scroll Actions:                                                    │   │
│   │  - scroll(start_box, end_box) # Scroll gesture                      │   │
│   │                                                                     │   │
│   │  Navigation Actions:                                                │   │
│   │  - press_home() / navigate_home()  # Home button                    │   │
│   │  - press_back() / navigate_back()  # Back button                    │   │
│   │  - open_app(content)               # Open application               │   │
│   │                                                                     │   │
│   │  Control Actions:                                                   │   │
│   │  - wait()                     # Wait/pause                          │   │
│   │  - finished(content)          # Mark task complete                  │   │
│   │  - answer(content)            # Provide answer                      │   │
│   │  - status(goal_status)        # Set completion status               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Action Execution:                                                         │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   Agent Output          AndroidEnvTool           RuntimeClient      │   │
│   │   ─────────────         ─────────────            ─────────────      │   │
│   │                                                                     │   │
│   │   "click(start_box=     parse action    ──▶     step({             │   │
│   │    '<|box_start|>       params                    "action_type":   │   │
│   │    (540,960)                                       "click",        │   │
│   │    <|box_end|>')"                                  "coordinate":   │   │
│   │                                                    [540, 960]      │   │
│   │                                                  })                │   │
│   │                                                        │           │   │
│   │                                                        ▼           │   │
│   │                         observation     ◀────   (obs, reward,      │   │
│   │                         (screenshot)             terminated, ...)  │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Data Flow

### Training Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Training Data Flow                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   1. Task Loading                                                           │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   JSONL Dataset File                                                │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │ {"task_id": 1, "seed": 0, "task": "Open Settings app", ...} │   │   │
│   │   │ {"task_id": 2, "seed": 0, "task": "Set alarm for 8am", ...} │   │   │
│   │   │ {"task_id": 3, "seed": 0, "task": "Send SMS to John", ...}  │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                          │                                          │   │
│   │                          ▼  AndroidWorldDataset                     │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │  {                                                          │   │   │
│   │   │    "instance_id": "1_0",                                    │   │   │
│   │   │    "instance": {...task data...},                           │   │   │
│   │   │    "data_source": "android_world",                          │   │   │
│   │   │    "raw_prompt": [{"role": "user", "content": "..."}]       │   │   │
│   │   │  }                                                          │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   2. Trajectory Generation                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   AndroidTrajectory.initialize_trajectory()                         │   │
│   │   ─────────────────────────────────────────                         │   │
│   │   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │   │
│   │   │ Allocate     │────▶│ RuntimeClient│────▶│ reset()      │        │   │
│   │   │ Container    │     │ .reset()     │     │ HTTP Request │        │   │
│   │   └──────────────┘     └──────────────┘     └──────────────┘        │   │
│   │                                                    │                │   │
│   │                                                    ▼                │   │
│   │                                             ┌──────────────┐        │   │
│   │                                             │ Initial      │        │   │
│   │                                             │ Screenshot   │        │   │
│   │                                             └──────────────┘        │   │
│   │                                                                     │   │
│   │   AndroidTrajectory.generate_trajectory()                           │   │
│   │   ───────────────────────────────────────                           │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │              Agent Loop (max_iterations)                    │   │   │
│   │   │                                                             │   │   │
│   │   │   Step 1:                                                   │   │   │
│   │   │   [Screenshot] ──▶ [VLM Generate] ──▶ [Parse Action]        │   │   │
│   │   │                                              │              │   │   │
│   │   │                                              ▼              │   │   │
│   │   │   [Accumulate Tensors] ◀── [Process] ◀── [Execute]         │   │   │
│   │   │                                              │              │   │   │
│   │   │                                              ▼              │   │   │
│   │   │   Step 2:                                                   │   │   │
│   │   │   [New Screenshot] ──▶ [VLM Generate] ──▶ ...               │   │   │
│   │   │                                                             │   │   │
│   │   │   ... (repeat until finished or max_iterations)             │   │   │
│   │   │                                                             │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   3. Training Tensor Output                                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   TrajectoryState (from agent.get_train_dict())                     │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │  input_ids:       [seq_len]        # Token IDs              │   │   │
│   │   │  labels:          [seq_len]        # -100 for prompt,       │   │   │
│   │   │                                    # token IDs for response │   │   │
│   │   │  attention_mask:  [seq_len]        # 1s and 0s              │   │   │
│   │   │  position_ids:    [3, seq_len]     # MROPE positions        │   │   │
│   │   │  pixel_values:    [N, C, H, W]     # Vision features        │   │   │
│   │   │  image_grid_thw:  [N, 3]           # Grid dimensions        │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                          │                                          │   │
│   │                          ▼  DataProto conversion                    │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │  DataProto {                                                │   │   │
│   │   │    batch: TensorDict(...training tensors...),               │   │   │
│   │   │    non_tensor_batch: {...rollout metrics...}                │   │   │
│   │   │  }                                                          │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                          │                                          │   │
│   │                          ▼  To VERL Trainer                         │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### VLM Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         VLM Processing Pipeline                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Message Format:                                                           │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  messages = [                                                       │   │
│   │    {"role": "system", "content": "You are a GUI agent..."},         │   │
│   │    {"role": "user", "content": [                                    │   │
│   │      {"type": "text", "text": "Task: Open Settings"},               │   │
│   │      {"type": "image", "image": <PIL.Image>}   # Screenshot         │   │
│   │    ]},                                                              │   │
│   │    {"role": "assistant", "content": "Thought: ...\nAction: ..."},   │   │
│   │    {"role": "user", "content": [                                    │   │
│   │      {"type": "image", "image": <PIL.Image>}   # New screenshot     │   │
│   │    ]},                                                              │   │
│   │    ...                                                              │   │
│   │  ]                                                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Processing Steps:                                                         │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   1. Apply Chat Template                                            │   │
│   │   ────────────────────────                                          │   │
│   │   messages ──▶ tokenizer.apply_chat_template() ──▶ text string      │   │
│   │                                                                     │   │
│   │   2. Replace Image Placeholders                                     │   │
│   │   ─────────────────────────────                                     │   │
│   │   "<|vision_start|>...<|vision_end|>" ──▶ "<|image_pad|>" tokens    │   │
│   │                                                                     │   │
│   │   3. Process with VLM Processor                                     │   │
│   │   ─────────────────────────────────                                 │   │
│   │   (text, images) ──▶ processor() ──▶ {                              │   │
│   │     input_ids: [seq_len],                                           │   │
│   │     attention_mask: [seq_len],                                      │   │
│   │     pixel_values: [N, C, H, W],                                     │   │
│   │     image_grid_thw: [N, 3]                                          │   │
│   │   }                                                                 │   │
│   │                                                                     │   │
│   │   4. Create Training Labels                                         │   │
│   │   ─────────────────────────                                         │   │
│   │   labels = input_ids.clone()                                        │   │
│   │   labels[prompt_positions] = -100  # Mask prompt tokens             │   │
│   │   labels[assistant_positions] = tokens  # Keep response tokens      │   │
│   │                                                                     │   │
│   │   5. Compute Position IDs (MROPE)                                   │   │
│   │   ────────────────────────────────                                  │   │
│   │   position_ids = get_rope_index(                                    │   │
│   │     input_ids, image_grid_thw, attention_mask                       │   │
│   │   )  # Returns [3, seq_len] for temporal, height, width             │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Configuration & Running

### Configuration File Structure

```yaml
# verl_android.yaml

# Agent and Task Classes
agent_cls: skyrl_agent.agents.android.AndroidAgent
task: skyrl_agent.tasks.android.android_task.AndroidTask

# Data Configuration (VLM image processing)
data:
  max_pixels: 1003520        # Maximum image pixels
  min_pixels: 3136           # Minimum image pixels

# Environment Configuration
env:
  pool_size: 8               # Number of Docker containers
  docker_image: androidworld:full_adb_agent
  snapshot: clean            # Emulator snapshot name
  sample_mode: sequential    # Task sampling: "random" or "sequential"
  train_task_family: android_world
  val_task_family: android_world
  temp_path: /tmp/androidworld

# Generator Configuration
generator:
  infer_backend: verl        # Backend: "verl", "openai", etc.
  num_trajectories: 8        # Trajectories per instance
  max_iterations: 30         # Max steps per trajectory
  max_prompt_length: 32768   # Max prompt tokens
  sampling_params:
    temperature: 1.0
    top_p: 1.0
    max_tokens: 4096
  vision_is_active: true     # Enable vision processing

# Dispatcher Configuration
dispatcher:
  type: async_fix_pool       # Dispatcher type
  max_parallel_agents: 8     # Max parallel trajectories
```

### Training Script

```bash
#!/bin/bash
# verl_android.sh

# Model configuration
MODEL_PATH="Qwen/Qwen2-VL-7B-Instruct"
EXPERIMENT_NAME="androidworld_training"

# GPU configuration
N_GPUS=8
N_GPUS_PER_NODE=8

# Run training
python -m skyrl_agent.integrations.verl.verl_main_ppo \
    --config examples/run_verl/verl_android.yaml \
    actor_rollout_ref.model.path=$MODEL_PATH \
    trainer.experiment_name=$EXPERIMENT_NAME \
    trainer.n_gpus_per_node=$N_GPUS_PER_NODE \
    trainer.total_epochs=10 \
    trainer.save_freq=1
```

### Inference Script

```bash
#!/bin/bash
# verl_android_inference.sh

MODEL_PATH="path/to/trained/model"
OUTPUT_DIR="outputs/inference"

python -m skyrl_agent.integrations.verl.verl_main_inference \
    --config examples/run_verl/verl_android_inference.yaml \
    actor_rollout_ref.model.path=$MODEL_PATH \
    trainer.output_dir=$OUTPUT_DIR
```

---

## 6. Practical Examples

### Example: Single Task Execution Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│           Example: "Open Settings and enable Dark Mode"                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Step 0: Initialize                                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Task: "Open Settings and enable Dark Mode"                         │   │
│   │  Container allocated: env_0                                         │   │
│   │  Initial screenshot: [Home screen]                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Step 1:                                                                   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Input: [Home screen screenshot]                                    │   │
│   │  Agent output:                                                      │   │
│   │    "Thought: I need to open the Settings app. I can see the         │   │
│   │     Settings icon on the home screen.                               │   │
│   │     Action: click(start_box='<|box_start|>(540,1200)<|box_end|>')"  │   │
│   │  Executed: click at (540, 1200)                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Step 2:                                                                   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Input: [Settings main screen screenshot]                           │   │
│   │  Agent output:                                                      │   │
│   │    "Thought: Settings is open. I need to find Display settings      │   │
│   │     to enable Dark Mode.                                            │   │
│   │     Action: click(start_box='<|box_start|>(540,600)<|box_end|>')"   │   │
│   │  Executed: click at (540, 600) - Display option                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Step 3:                                                                   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Input: [Display settings screenshot]                               │   │
│   │  Agent output:                                                      │   │
│   │    "Thought: I can see the Dark theme option. I'll click on it      │   │
│   │     to enable dark mode.                                            │   │
│   │     Action: click(start_box='<|box_start|>(540,400)<|box_end|>')"   │   │
│   │  Executed: click at (540, 400) - Dark theme toggle                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Step 4:                                                                   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Input: [Display settings with Dark theme enabled]                  │   │
│   │  Agent output:                                                      │   │
│   │    "Thought: Dark mode is now enabled. The task is complete.        │   │
│   │     Action: finished(content='')"                                   │   │
│   │  Result: Task completed successfully                                │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Evaluation:                                                               │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  - Task evaluator checks if Dark Mode is enabled                    │   │
│   │  - Reward: 1.0 (success)                                            │   │
│   │  - Steps taken: 4                                                   │   │
│   │  - Container released back to pool                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Example: Parallel Trajectory Execution

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              Parallel Execution: 8 Trajectories, 4 Containers               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Time ──────────────────────────────────────────────────────────────────▶  │
│                                                                             │
│   Container 0: │ traj_0 ████████████│ traj_4 ██████████│                    │
│   Container 1: │ traj_1 ██████████████│ traj_5 ████████│                    │
│   Container 2: │ traj_2 ████████│ traj_6 ████████████████│                  │
│   Container 3: │ traj_3 ██████████████████│ traj_7 ██████│                  │
│                                                                             │
│   Legend:                                                                   │
│   █ = Trajectory execution (initialize → generate → evaluate)              │
│   │ = Container idle, waiting for next trajectory                          │
│                                                                             │
│   Dispatcher (async_fix_pool):                                              │
│   1. Allocates traj_0-3 to containers 0-3 (parallel start)                  │
│   2. When container finishes, immediately allocates next trajectory         │
│   3. Container 2 finishes first → gets traj_4... wait, traj_4 to container 0│
│   4. Continues until all 8 trajectories complete                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Summary

The SkyRL-AndroidWorld integration demonstrates how the SkyRL-Agent framework can be extended to support complex GUI agent tasks:

1. **Agent Layer**: `AndroidAgent` uses VLM for visual understanding and action generation, `AndroidTrajectory` orchestrates the lifecycle, and `AndroidAgentRunner` manages parallel execution.

2. **Environment Layer**: `AndroidTask` provides the task interface, `ContainerManager` handles Docker container pooling, and `RuntimeClient` enables HTTP communication with Android emulators.

3. **Tools**: `AndroidEnvTool` translates agent actions into environment commands.

4. **Data Flow**: Task instances flow from JSONL datasets through trajectory generation to training tensors compatible with VERL's PPO/GRPO training.

This architecture enables efficient training of GUI agents on AndroidWorld tasks with parallel environment execution and seamless integration with the VERL training backend.
