# SkyRL-Agent Framework Tutorial

## 1. Introduction

### What is SkyRL-Agent?

SkyRL-Agent is a unified framework for training and evaluating modern AI agents with modular tasks, tools, and backends. It provides a flexible architecture that enables researchers and engineers to:

- Train agents using multiple backends (VERL, SkyRL-Train, Tinker, OpenAI-compatible)
- Support diverse agent architectures (ReAct, CodeAct, Android GUI agents)
- Implement efficient async dispatching strategies for parallel execution
- Create pluggable tools and tasks for various domains

### Design Philosophy

The framework is built around several core principles:

1. **Modularity**: Each component (agents, tasks, tools, backends) can be swapped independently
2. **Async-First**: All operations are designed for asynchronous execution to maximize throughput
3. **Configuration-Driven**: Behavior is controlled via YAML configs and Hydra, enabling reproducibility
4. **Pluggability**: New components can be added via simple registration decorators

### Supported Agent Types

| Agent Type | Description | Use Case |
|------------|-------------|----------|
| **ReActAgent** | Reasoning + Acting pattern | General task solving |
| **CodeActAgent** | OpenHands-based code execution | Software engineering tasks |
| **AndroidAgent** | GUI automation agent | Mobile app automation, AndroidWorld |

### Supported Backends

| Backend | Description |
|---------|-------------|
| **VERL** | Primary training backend with PPO/GRPO support |
| **SkyRL-Train** | Alternative training backend |
| **Tinker** | Lightweight training backend |
| **OpenAI** | Inference-only via LiteLLM |

---

## 3. Architecture Overview

### 3.1 Three-Layer Architecture

The SkyRL-Agent framework is organized into three layers. Let's start with the high-level view before diving into details.

#### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND LAYER                                       │
│                                                                                  │
│     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────┐    │
│     │    VERL     │     │ SkyRL-Train │     │   Tinker    │     │ OpenAI  │    │
│     │  (PPO/GRPO) │     │             │     │             │     │         │    │
│     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └────┬────┘    │
│            │                   │                   │                 │          │
│            └───────────────────┴───────────────────┴─────────────────┘          │
│                                        │                                         │
│                                        ▼                                         │
│            ┌───────────────────────────────────────────────────────┐            │
│            │              Unified Interface                        │            │
│            │                                                       │            │
│            │   AsyncInferBackend    GeneratorInput   GeneratorOutput│            │
│            │   - generate_prompts() - input_batch    - result      │            │
│            │   - generate_ids()                      - tokens      │            │
│            │                                         - rewards     │            │
│            └───────────────────────────┬───────────────────────────┘            │
│                                        │                                         │
└────────────────────────────────────────┼────────────────────────────────────────┘
                                         │
                                         │ GeneratorInput / GeneratorOutput
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               AGENT LAYER                                        │
│                                                                                  │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────────────────────────┐  │
│  │ AgentRunner │─────►│ Dispatcher  │─────►│         Trajectory              │  │
│  │   (Batch)   │      │  (Shared)   │      │         (Episode)               │  │
│  └─────────────┘      └─────────────┘      └───────────────┬─────────────────┘  │
│                                                            │                     │
│                                                            ▼                     │
│                                            ┌───────────────────────────────┐     │
│                                            │           Agents              │     │
│                                            │  ┌───────┐┌───────┐┌───────┐ │     │
│                                            │  │ ReAct ││CodeAct││Android│ │     │
│                                            │  └───────┘└───────┘└───────┘ │     │
│                                            └───────────────┬───────────────┘     │
│                                                            │                     │
└────────────────────────────────────────────────────────────┼────────────────────┘
                                                             │ Actions
                                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            ENVIRONMENT LAYER                                     │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                              Tasks                                      │    │
│  │   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              │    │
│  │   │ AndroidTask │     │  SWEBench   │     │ WebResearch │    ...       │    │
│  │   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘              │    │
│  │          │                   │                   │                      │    │
│  │          ▼                   ▼                   ▼                      │    │
│  │   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              │    │
│  │   │   Runtime   │     │   Runtime   │     │   Runtime   │              │    │
│  │   │  (Docker)   │     │ (Sandbox)   │     │ (Browser)   │              │    │
│  │   └─────────────┘     └─────────────┘     └─────────────┘              │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                          │                                       │
│                                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                              Tools                                      │    │
│  │   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐          │    │
│  │   │android_env│  │  search   │  │web_browser│  │  finish   │   ...    │    │
│  │   └───────────┘  └───────────┘  └───────────┘  └───────────┘          │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                          │                                       │
│                                          ▼ Observations                          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Key Concept: Backend Abstraction**

The Backend Layer provides a unified interface that abstracts away different training/inference backends:

| Backend | Use Case | Data Format Handling |
|---------|----------|---------------------|
| **VERL** | Distributed PPO/GRPO training | `DataProto` ↔ `GeneratorInput/Output` |
| **SkyRL-Train** | Alternative training | Custom format ↔ `GeneratorInput/Output` |
| **Tinker** | Lightweight training | Custom format ↔ `GeneratorInput/Output` |
| **OpenAI** | Inference only (via LiteLLM) | API format ↔ `GeneratorInput/Output` |

**Data Format Conversion:**

```
Backend-specific format                    Agent Layer format
        │                                         │
        ▼                                         ▼
┌───────────────────┐                   ┌───────────────────┐
│  VERL: DataProto  │                   │  GeneratorInput   │
│  - batch tensor   │ ──── convert ──── │  - input_batch    │
│  - meta_info      │                   │                   │
└───────────────────┘                   └───────────────────┘

┌───────────────────┐                   ┌───────────────────┐
│  GeneratorOutput  │                   │  VERL: DataProto  │
│  - tokens         │ ──── convert ──── │  - TensorDict     │
│  - rewards        │                   │  - rewards        │
│  - masks          │                   │  - masks          │
└───────────────────┘                   └───────────────────┘
```

---

#### Detailed View: Inference / Rollout Collection

Now let's examine each layer in detail during rollout collection.

##### Backend Layer Details

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND LAYER                                       │
│                                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                         SkyAgentPPOTrainer                                │  │
│  │                                                                           │  │
│  │   - Orchestrates training loop                                           │  │
│  │   - Calls generate_sequences() for rollout                               │  │
│  │   - Receives DataProto, performs PPO update                              │  │
│  └─────────────────────────────────┬─────────────────────────────────────────┘  │
│                                    │                                             │
│                                    │ generate_sequences(DataProto)               │
│                                    ▼                                             │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                         SkyAgentLoopManager                               │  │
│  │                                                                           │  │
│  │   - Coordinates rollout collection                                       │  │
│  │   - Owns and manages inference servers                                   │  │
│  │   - Owns AgentRunner instance                                            │  │
│  │   - Post-processes results: _postprocess() → DataProto                   │  │
│  └──────────┬────────────────────────────────────────┬───────────────────────┘  │
│             │                                        │                           │
│             │ owns                                   │ owns                      │
│             ▼                                        ▼                           │
│  ┌─────────────────────────┐          ┌─────────────────────────────────────┐   │
│  │     AgentRunner         │          │       AsyncLLMServerManager         │   │
│  │                         │          │                                     │   │
│  │  (passed to Agent Layer)│          │  ┌─────────────────────────────┐   │   │
│  └─────────────────────────┘          │  │  SkyAgentAsyncvLLMServer    │   │   │
│                                       │  │  (Ray Actor, DP Rank 0)     │   │   │
│                                       │  │                             │   │   │
│                                       │  │  - vLLM AsyncEngine         │   │   │
│                                       │  │  - GPU inference            │   │   │
│                                       │  │  - generate(prompt_ids)     │   │   │
│                                       │  └─────────────────────────────┘   │   │
│                                       │               ...                   │   │
│                                       │  ┌─────────────────────────────┐   │   │
│                                       │  │  SkyAgentAsyncvLLMServer    │   │   │
│                                       │  │  (Ray Actor, DP Rank N)     │   │   │
│                                       │  └─────────────────────────────┘   │   │
│                                       └─────────────────┬───────────────────┘   │
│                                                         │                        │
└─────────────────────────────────────────────────────────┼────────────────────────┘
                                                          │
                                                          │ Output to Agent Layer:
                                                          │ - generate(prompt_ids, sampling_params)
                                                          │ - Returns: text, output_tokens, finish_reason
                                                          ▼
                                                   ┌─────────────┐
                                                   │ AGENT LAYER │
                                                   └─────────────┘
```

##### Agent Layer Details

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               AGENT LAYER                                        │
│                                                                                  │
│  Input from Backend: run(batch), inference engine reference                     │
│                                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                            AgentRunner                                    │  │
│  │                                                                           │  │
│  │   - Loads task YAML configuration                                        │  │
│  │   - Creates TrajectoryConfig for each (instance_id, trajectory_id)       │  │
│  │   - Maintains: trajectories[instance_id][trajectory_id] = BaseTrajectory │  │
│  │   - Calls _post_process_results() to collect training data               │  │
│  └──────────────────────────────────┬────────────────────────────────────────┘  │
│                                     │                                            │
│                                     │ dispatches trajectories                    │
│                                     ▼                                            │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                            Dispatcher                                     │  │
│  │                                                                           │  │
│  │   ┌─────────────────────────┐    ┌─────────────────────────────────────┐ │  │
│  │   │    async_pipeline       │    │         async_fix_pool              │ │  │
│  │   │                         │    │                                     │ │  │
│  │   │  Three queues:          │    │  Fixed environment pool:            │ │  │
│  │   │  init → run → eval      │    │  - Pre-initialized envs             │ │  │
│  │   │                         │    │  - Worker per env                   │ │  │
│  │   │  Best for: varied       │    │  - Reuse across trajectories        │ │  │
│  │   │  resource needs         │    │                                     │ │  │
│  │   └─────────────────────────┘    │  Best for: expensive setup          │ │  │
│  │                                  │  (e.g., Docker containers)          │ │  │
│  │                                  └─────────────────────────────────────┘ │  │
│  └──────────────────────────────────┬────────────────────────────────────────┘  │
│                                     │                                            │
│                                     │ executes lifecycle methods                 │
│                                     ▼                                            │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                          BaseTrajectory                                   │  │
│  │                                                                           │  │
│  │   Lifecycle:                                                              │  │
│  │   ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────┐  │  │
│  │   │ initialize_         │  │ generate_           │  │ evaluate_       │  │  │
│  │   │ trajectory()        │─►│ trajectory()        │─►│ trajectory()    │  │  │
│  │   │                     │  │                     │  │                 │  │  │
│  │   │ - Get instruction   │  │ - Run agent loop    │  │ - Compute reward│  │  │
│  │   │ - Setup agent       │  │ - Collect messages  │  │ - Set finish    │  │  │
│  │   └─────────────────────┘  └──────────┬──────────┘  └─────────────────┘  │  │
│  │                                       │                                   │  │
│  └───────────────────────────────────────┼───────────────────────────────────┘  │
│                                          │                                       │
│                                          │ runs                                  │
│                                          ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                              Agent                                        │  │
│  │                                                                           │  │
│  │   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                │  │
│  │   │  ReActAgent │     │ CodeActAgent│     │AndroidAgent │    ...         │  │
│  │   └─────────────┘     └─────────────┘     └──────┬──────┘                │  │
│  │                                                  │                        │  │
│  │   Agent Loop (inside generate_trajectory):      │                        │  │
│  │   ┌──────────────────────────────────────────────┴─────────────────────┐ │  │
│  │   │  while not done and step < max_iterations:                         │ │  │
│  │   │      1. Format messages (system + history + observation)           │ │  │
│  │   │      2. Call inference engine → LLM response                       │ │  │
│  │   │      3. Parse action from response                                 │ │  │
│  │   │      4. Execute tool (action) ──────────────────────────────────────┼─┼──►
│  │   │      5. Receive observation ◄───────────────────────────────────────┼─┼──
│  │   │      6. Update state (messages, step_count)                        │ │  │
│  │   │      7. Check termination (finish action, max_iter, error)         │ │  │
│  │   └────────────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  Output to Environment Layer:                                                   │
│  - Action: {tool_name: str, params: dict}                                       │
│  - Example: {tool: "android_env", params: {action: "click", coordinate: (x,y)}} │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                                   ┌──────────────────┐
                                   │ ENVIRONMENT LAYER│
                                   └──────────────────┘
```

##### Environment Layer Details

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            ENVIRONMENT LAYER                                     │
│                                                                                  │
│  Input from Agent Layer: Action {tool_name, params}                             │
│                                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                             BaseTask                                      │  │
│  │                                                                           │  │
│  │   Interface Methods:                                                      │  │
│  │   - initialize_runtime() → Create and manage runtime pool                │  │
│  │   - get_instruction()    → Return initial task instruction               │  │
│  │   - evaluate_result()    → Compute reward based on final state           │  │
│  │                                                                           │  │
│  │   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐        │  │
│  │   │   AndroidTask   │   │   SWEBenchTask  │   │ WebResearchTask │  ...   │  │
│  │   └────────┬────────┘   └────────┬────────┘   └────────┬────────┘        │  │
│  │            │                     │                     │                  │  │
│  └────────────┼─────────────────────┼─────────────────────┼──────────────────┘  │
│               │                     │                     │                      │
│               ▼                     ▼                     ▼                      │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                        Runtime Pool / Environment Pool                    │  │
│  │                                                                           │  │
│  │   AndroidTask Runtime (ContainerManager):                                │  │
│  │   ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │   │                     Docker Container Pool                       │    │  │
│  │   │                                                                 │    │  │
│  │   │   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │    │  │
│  │   │   │Container │  │Container │  │Container │  │Container │ ...  │    │  │
│  │   │   │  Env 0   │  │  Env 1   │  │  Env 2   │  │  Env N   │      │    │  │
│  │   │   │          │  │          │  │          │  │          │      │    │  │
│  │   │   │ Android  │  │ Android  │  │ Android  │  │ Android  │      │    │  │
│  │   │   │ Emulator │  │ Emulator │  │ Emulator │  │ Emulator │      │    │  │
│  │   │   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘      │    │  │
│  │   │        │             │             │             │             │    │  │
│  │   │        └─────────────┴──────┬──────┴─────────────┘             │    │  │
│  │   │                             │                                  │    │  │
│  │   │                    RuntimeClient per container                 │    │  │
│  │   │                    - reset(), step(), get_screenshot()         │    │  │
│  │   └─────────────────────────────┼───────────────────────────────────┘    │  │
│  │                                 │                                        │  │
│  │   SWEBench Runtime:             │    WebResearch Runtime:                │  │
│  │   ┌─────────────────────┐       │    ┌─────────────────────┐            │  │
│  │   │   Sandbox Pool      │       │    │   Browser Pool      │            │  │
│  │   │   - Code execution  │       │    │   - Headless Chrome │            │  │
│  │   │   - Git operations  │       │    │   - Page navigation │            │  │
│  │   └─────────────────────┘       │    └─────────────────────┘            │  │
│  │                                 │                                        │  │
│  └─────────────────────────────────┼────────────────────────────────────────┘  │
│                                    │                                            │
│                                    │ Parallel execution via pool               │
│                                    ▼                                            │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                             BaseTool                                      │  │
│  │                                                                           │  │
│  │   Interface:                                                              │  │
│  │   - call(params, runtime) → Execute action, return observation           │  │
│  │                                                                           │  │
│  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │  │
│  │   │ android_env │  │   search    │  │ web_browser │  │   finish    │     │  │
│  │   │             │  │             │  │             │  │             │     │  │
│  │   │ Actions:    │  │ Actions:    │  │ Actions:    │  │ Actions:    │     │  │
│  │   │ - click     │  │ - query     │  │ - navigate  │  │ - complete  │     │  │
│  │   │ - type      │  │ - get_results│ │ - click     │  │ - answer    │     │  │
│  │   │ - scroll    │  │             │  │ - extract   │  │             │     │  │
│  │   │ - press_back│  │             │  │             │  │             │     │  │
│  │   └──────┬──────┘  └─────────────┘  └─────────────┘  └─────────────┘     │  │
│  │          │                                                                │  │
│  └──────────┼────────────────────────────────────────────────────────────────┘  │
│             │                                                                    │
│             │ Output to Agent Layer:                                            │
│             │ Observation: {screenshot, status, error, done}                    │
│             ▼                                                                    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Parallel Execution Model:**

```
                            AgentRunner
                                 │
                                 │ dispatches N trajectories
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Dispatcher                              │
│                      (async_fix_pool)                           │
│                                                                 │
│   Work Queue: [(inst_0, traj_0), (inst_0, traj_1), ...]        │
│                                                                 │
│        │              │              │              │           │
│        ▼              ▼              ▼              ▼           │
│   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐       │
│   │Worker 0 │   │Worker 1 │   │Worker 2 │   │Worker N │       │
│   └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘       │
└────────┼─────────────┼─────────────┼─────────────┼─────────────┘
         │             │             │             │
         ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Environment Pool                             │
│                                                                 │
│   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐       │
│   │  Env 0  │   │  Env 1  │   │  Env 2  │   │  Env N  │       │
│   │(Docker) │   │(Docker) │   │(Docker) │   │(Docker) │       │
│   └─────────┘   └─────────┘   └─────────┘   └─────────┘       │
│                                                                 │
│   - Each worker claims one env from pool                       │
│   - Executes full trajectory (init → run → eval)               │
│   - Returns env to pool when done                              │
│   - Next trajectory claims freed env                           │
└─────────────────────────────────────────────────────────────────┘
```

---

#### Detailed View: Training Phase

After rollout collection, data flows back to the trainer:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         ROLLOUT OUTPUT (from Agent Layer)                        │
│                                                                                  │
│   AgentRunner._post_process_results() produces:                                 │
│   ┌───────────────────────────────────────────────────────────────────────────┐ │
│   │  {                                                                        │ │
│   │    "prompt_token_ids": List[List[int]],    # Tokenized prompts           │ │
│   │    "response_ids": List[List[int]],        # Tokenized responses         │ │
│   │    "rewards": List[float],                 # Per-step rewards            │ │
│   │    "traj_rewards": List[float],            # Per-trajectory rewards      │ │
│   │    "loss_masks": List[List[int]],          # Which tokens to train on    │ │
│   │    "rollout_logprobs": List[List[float]],  # Log probs from rollout      │ │
│   │    "rollout_metrics": Dict[str, float]     # Metrics for logging         │ │
│   │  }                                                                        │ │
│   └───────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    SkyAgentLoopManager._postprocess()                            │
│                                                                                  │
│   Converts to VERL DataProto:                                                   │
│   ┌───────────────────────────────────────────────────────────────────────────┐ │
│   │  TensorDict:                                                              │ │
│   │    prompts:        Tensor[bsz, prompt_len]     # Left-padded             │ │
│   │    responses:      Tensor[bsz, response_len]   # Right-padded            │ │
│   │    response_mask:  Tensor[bsz, response_len]   # Loss mask               │ │
│   │    input_ids:      Tensor[bsz, total_len]      # Full sequence           │ │
│   │    attention_mask: Tensor[bsz, total_len]                                │ │
│   │    position_ids:   Tensor[bsz, 4, total_len]   # VLM 4D positions        │ │
│   │                                                                           │ │
│   │  non_tensor_batch:                                                        │ │
│   │    rewards:            np.array[bsz]                                      │ │
│   │    multi_modal_inputs: np.array[bsz]           # VLM pixel values        │ │
│   └───────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         │ DataProto
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        BACKEND LAYER: Training Loop                              │
│                                                                                  │
│   SkyAgentPPOTrainer.fit():                                                     │
│   ┌───────────────────────────────────────────────────────────────────────────┐ │
│   │                                                                           │ │
│   │   1. Receive DataProto from generate_sequences()                         │ │
│   │                                                                           │ │
│   │   2. Compute Advantages (GRPO or GAE):                                   │ │
│   │      GRPO: advantages = rewards - mean(rewards)                          │ │
│   │                                                                           │ │
│   │   3. PPO Policy Update:                                                  │ │
│   │      actor_rollout_wg.update_actor(DataProto)                            │ │
│   │      Loss = -min(ratio * adv, clip(ratio, 1-ε, 1+ε) * adv)              │ │
│   │                                                                           │ │
│   │   4. Sync Weights to Inference Engine:                                   │ │
│   │      actor_rollout_wg.update_rollout()                                   │ │
│   │                                                                           │ │
│   └───────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Training Data Flow:**
```
DataProto (from rollout)
    │
    ▼
SkyAgentPPOTrainer.fit()
    │
    ├──► compute_advantage() → advantages tensor
    │
    ├──► actor_rollout_wg.update_actor()
    │         ├──► Forward: compute new log probs
    │         ├──► PPO loss with clipped objective
    │         └──► Backward: gradient update (FSDP)
    │
    └──► actor_rollout_wg.update_rollout()
              └──► Sync weights to inference engine
```


### 3.2 Layer Interface Diagram with Data Structures

This section details the data structures passed between each layer:

```
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND LAYER                               │
│                                                                  │
│   Input:  GeneratorInput                                        │
│           └── input_batch: List[Dict]  (raw training data)      │
│                                                                  │
│   Output: GeneratorOutput                                       │
│           └── result: Dict                                      │
│               ├── prompt_token_ids: List[List[int]]             │
│               ├── response_ids: List[List[int]]                 │
│               ├── rewards: List[float]                          │
│               ├── loss_masks: List[List[int]]                   │
│               ├── rollout_logprobs: List[List[float]]           │
│               └── rollout_metrics: Dict[str, float]             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT LAYER                                 │
│                                                                  │
│   TrajectoryConfig (input configuration):                       │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  instance_id: int          # Unique instance identifier │   │
│   │  trajectory_id: int        # Trajectory index           │   │
│   │  max_prompt_length: int    # Token limit (default 1024) │   │
│   │  max_iterations: int       # Max agent steps            │   │
│   │  sampling_params: Dict     # LLM sampling config        │   │
│   │  vision_is_active: bool    # Enable vision model        │   │
│   │  tools: List[str]          # Enabled tool names         │   │
│   │  agent_cls: str            # Agent class path           │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   TrajectoryResult (output after trajectory):                   │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  instance_id: str          # Instance identifier        │   │
│   │  trajectory_id: str        # Trajectory identifier      │   │
│   │  messages: List[Dict]      # Conversation history       │   │
│   │  state: Any                # Agent internal state       │   │
│   │  finish: bool              # Task completion flag       │   │
│   │  finish_reason: str        # Why trajectory ended       │   │
│   │  reward: float             # Evaluation reward          │   │
│   │  error: Optional[str]      # Error message if failed    │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ENVIRONMENT LAYER                              │
│                                                                  │
│   Action (Agent → Environment):                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  tool_name: str            # e.g., "android_env"        │   │
│   │  params: Dict              # Tool-specific parameters   │   │
│   │    ├── action_type: str    # e.g., "click", "type"      │   │
│   │    ├── coordinate: Tuple   # (x, y) for click actions   │   │
│   │    └── content: str        # Text for type actions      │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   Observation (Environment → Agent):                            │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  screenshot: bytes/str     # Base64 encoded image       │   │
│   │  status: str               # Action execution status    │   │
│   │  error: Optional[str]      # Error if action failed     │   │
│   │  done: bool                # Episode termination flag   │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 Interface Diagrams

#### BaseTrajectory Interface

```
┌─────────────────────────────────────────────────────────────────┐
│                     BaseTrajectory (ABC)                         │
├─────────────────────────────────────────────────────────────────┤
│  Attributes:                                                     │
│  ─────────────                                                   │
│  + cfg: TrajectoryConfig      # Configuration                   │
│  + data: Dict[str, Any]       # Instance data                   │
│  + infer_engine: AsyncInferBackend  # LLM backend               │
│  + tokenizer: AutoTokenizer   # Text tokenizer                  │
│  + task: BaseTask             # Task reference                  │
│  + val_mode: bool             # Validation mode flag            │
│  + result: TrajectoryResult   # Output result                   │
├─────────────────────────────────────────────────────────────────┤
│  Lifecycle Methods:                                              │
│  ─────────────────                                               │
│  + async initialize_trajectory() → None                         │
│      │  Setup agent, load instruction, prepare environment      │
│      ▼                                                           │
│  + async generate_trajectory() → None                           │
│      │  Run agent loop: inference → action → observation        │
│      ▼                                                           │
│  + async evaluate_trajectory() → None                           │
│         Evaluate result, compute reward                          │
└─────────────────────────────────────────────────────────────────┘
```

#### AgentRunner Interface

```
┌─────────────────────────────────────────────────────────────────┐
│                       AgentRunner                                │
├─────────────────────────────────────────────────────────────────┤
│  Attributes:                                                     │
│  ─────────────                                                   │
│  + cfg: Dict[str, Any]        # Full configuration              │
│  + infer_engine: AsyncInferBackend  # Built backend             │
│  + tokenizer: AutoTokenizer   # Tokenizer instance              │
│  + traj_cls: Type[BaseTrajectory]  # Trajectory class           │
│  + task: BaseTask             # Task instance                   │
│  + trajectories: Dict[str, Dict[str, BaseTrajectory]]           │
├─────────────────────────────────────────────────────────────────┤
│  Methods:                                                        │
│  ────────                                                        │
│  + from_task(task, infer_engine, tokenizer) → AgentRunner       │
│      Class method: Create runner from task YAML path            │
│                                                                  │
│  + async run(input_batch, val_mode=False) → GeneratorOutput     │
│      Main entry point:                                           │
│      1. Build GeneratorInput from batch                         │
│      2. Initialize trajectories via _initialize_trajectories()  │
│      3. Dispatch via DISPATCHER_REGISTRY                        │
│      4. Post-process via _post_process_results()                │
│      5. Return GeneratorOutput                                  │
│                                                                  │
│  - _get_data(content) → Dict[str, Any]                          │
│      Extract instance, instance_id, data_source from content    │
│                                                                  │
│  - _initialize_trajectories(val_mode) → None                    │
│      Create BaseTrajectory instances for each (instance, traj)  │
│                                                                  │
│  - _post_process_results(val_mode) → Dict[str, Any]             │
│      Convert trajectory results to training tensors             │
└─────────────────────────────────────────────────────────────────┘
```

#### BaseTask Interface

```
┌─────────────────────────────────────────────────────────────────┐
│                       BaseTask (ABC)                             │
├─────────────────────────────────────────────────────────────────┤
│  Class Methods:                                                  │
│  ──────────────                                                  │
│  + async initialize_runtime(*args, **kwargs) → Any              │
│      │  Initialize runtime environment (e.g., Docker pool)      │
│      │  Returns: Runtime handle(s) for dispatcher               │
│      │                                                           │
│      │  Example (AndroidTask):                                   │
│      │  - Creates ContainerManager                               │
│      │  - Spawns Docker container pool                           │
│      │  - Returns List[RuntimeClient]                            │
│      ▼                                                           │
│  + get_instruction(*args, **kwargs) → List[Dict[str, str]]      │
│      │  Get initial instruction in OpenAI messages format       │
│      │  Returns: [{"role": "user", "content": "..."}]           │
│      ▼                                                           │
│  + complete_runtime(*args, **kwargs) → Dict[str, Any]           │
│      │  Finalize runtime (e.g., extract git patch)              │
│      │  Returns: Completion artifacts                            │
│      ▼                                                           │
│  + async evaluate_result(*args, **kwargs) → bool                │
│         Evaluate trajectory result                               │
│         Returns: True if task succeeded, False otherwise         │
└─────────────────────────────────────────────────────────────────┘
```

#### BaseTool Interface

```
┌─────────────────────────────────────────────────────────────────┐
│                       BaseTool (ABC)                             │
├─────────────────────────────────────────────────────────────────┤
│  Class Attributes:                                               │
│  ─────────────────                                               │
│  + name: str                  # Tool identifier                 │
│  + description: str           # Human-readable description      │
│  + parameters: dict           # JSON schema for parameters      │
├─────────────────────────────────────────────────────────────────┤
│  Methods:                                                        │
│  ────────                                                        │
│  + __init__(cfg: Optional[dict])                                │
│      Initialize tool with optional configuration                 │
│                                                                  │
│  + call(params: Union[str, dict], **kwargs) → Union[str, dict]  │
│      Execute tool action                                         │
│      - params: Tool parameters (JSON string or dict)            │
│      - Returns: Tool execution result                           │
│                                                                  │
│  + get_tool_param() → ChatCompletionToolParam                   │
│      Get OpenAI-compatible tool definition                       │
│                                                                  │
│  + get_system_prompt_prefix() → Optional[str]                   │
│      Optional system prompt addition for this tool              │
├─────────────────────────────────────────────────────────────────┤
│  Registration:                                                   │
│  ─────────────                                                   │
│  @register_tool("tool_name")                                    │
│  class MyTool(BaseTool):                                        │
│      name = "tool_name"                                         │
│      ...                                                         │
└─────────────────────────────────────────────────────────────────┘
```

#### AsyncInferBackend Interface

```
┌─────────────────────────────────────────────────────────────────┐
│                   AsyncInferBackend (ABC)                        │
├─────────────────────────────────────────────────────────────────┤
│  Abstract Methods:                                               │
│  ─────────────────                                               │
│  + async async_generate_prompts(                                │
│        prompts: Any,                                            │
│        sampling_params: Any,                                    │
│        **kwargs                                                 │
│    ) → List[str]                                                │
│      Generate outputs from text prompts                          │
│      - prompts: List of prompt strings or message lists         │
│      - sampling_params: Temperature, top_p, max_tokens, etc.    │
│      - Returns: List of generated text responses                │
│                                                                  │
│  + async async_generate_ids(                                    │
│        input_ids: Any,                                          │
│        sampling_params: Any,                                    │
│        **kwargs                                                 │
│    ) → List[str]                                                │
│      Generate outputs from token IDs                             │
│      - input_ids: List of token ID sequences                    │
│      - sampling_params: Generation parameters                   │
│      - Returns: List of generated text responses                │
├─────────────────────────────────────────────────────────────────┤
│  Supporting Classes:                                             │
│  ───────────────────                                             │
│  GeneratorInput:                                                 │
│    + input_batch: Any         # Processed input data            │
│                                                                  │
│  GeneratorOutput:                                                │
│    + result: Any              # Processed output data           │
│                                                                  │
│  BackendSpec:                                                    │
│    + infer_backend_cls: Type[AsyncInferBackend]                 │
│    + generator_output_cls: Type[GeneratorOutput]                │
│    + generator_input_cls: Type[GeneratorInput]                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.4 Component Interaction Sequence Diagram

```
┌────────┐     ┌───────────┐     ┌──────────────┐     ┌────────┐     ┌─────────────┐
│ VERL   │     │AgentRunner│     │BaseTrajectory│     │  Agent │     │ Environment │
│Trainer │     │           │     │              │     │        │     │  (Task)     │
└───┬────┘     └─────┬─────┘     └──────┬───────┘     └───┬────┘     └──────┬──────┘
    │                │                  │                 │                 │
    │  run(batch)    │                  │                 │                 │
    │───────────────>│                  │                 │                 │
    │                │                  │                 │                 │
    │                │ _initialize_trajectories()        │                 │
    │                │─────────────────>│                 │                 │
    │                │                  │                 │                 │
    │                │    Dispatcher: initialize_trajectory()              │
    │                │─────────────────>│                 │                 │
    │                │                  │                 │                 │
    │                │                  │  get_instruction()               │
    │                │                  │────────────────────────────────>│
    │                │                  │<────────────────────────────────│
    │                │                  │  instruction messages            │
    │                │                  │                 │                 │
    │                │    Dispatcher: generate_trajectory()                │
    │                │─────────────────>│                 │                 │
    │                │                  │                 │                 │
    │                │                  │ ┌─────────────────────────────┐  │
    │                │                  │ │    AGENT LOOP               │  │
    │                │                  │ │  ┌─────────────────────────┐│  │
    │                │                  │ │  │ 1. Format messages      ││  │
    │                │                  │ │  │ 2. Call LLM inference   ││  │
    │                │                  │ │  │ 3. Parse action         ││  │
    │                │                  │ │  │ 4. Execute tool         │───>│
    │                │                  │ │  │ 5. Get observation      │<───│
    │                │                  │ │  │ 6. Update state         ││  │
    │                │                  │ │  │ 7. Check termination    ││  │
    │                │                  │ │  └─────────────────────────┘│  │
    │                │                  │ │  Repeat until done          │  │
    │                │                  │ └─────────────────────────────┘  │
    │                │                  │                 │                 │
    │                │    Dispatcher: evaluate_trajectory()                │
    │                │─────────────────>│                 │                 │
    │                │                  │                 │                 │
    │                │                  │  evaluate_result()               │
    │                │                  │────────────────────────────────>│
    │                │                  │<────────────────────────────────│
    │                │                  │  reward: bool                    │
    │                │                  │                 │                 │
    │                │ _post_process_results()           │                 │
    │                │<─────────────────│                 │                 │
    │                │                  │                 │                 │
    │  GeneratorOutput                  │                 │                 │
    │<───────────────│                  │                 │                 │
    │                │                  │                 │                 │
    │  PPO Update    │                  │                 │                 │
    │  (training)    │                  │                 │                 │
    │                │                  │                 │                 │
```

---

### 3.5 Async Inference: How AsyncLLMServerManager Works

In VERL's async rollout mode, multiple vLLM engines run in parallel to handle concurrent inference requests from multiple trajectories. The `AsyncLLMServerManager` coordinates request routing to available engines.

#### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         SkyAgentLoopManager                                      │
│                                                                                  │
│   Creates and owns:                                                             │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                      AsyncLLMServerManager                              │   │
│   │                                                                         │   │
│   │   - Wraps multiple vLLM server instances                               │   │
│   │   - Routes requests to available servers                               │   │
│   │   - Provides unified generate() interface                              │   │
│   │                                                                         │   │
│   │   Server Pool:                                                          │   │
│   │   ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐          │   │
│   │   │  vLLM Server 0  │ │  vLLM Server 1  │ │  vLLM Server N  │          │   │
│   │   │  (DP Rank 0)    │ │  (DP Rank 1)    │ │  (DP Rank N)    │          │   │
│   │   │                 │ │                 │ │                 │          │   │
│   │   │  Ray Actor      │ │  Ray Actor      │ │  Ray Actor      │          │   │
│   │   │  GPU 0          │ │  GPU 1          │ │  GPU N          │          │   │
│   │   └─────────────────┘ └─────────────────┘ └─────────────────┘          │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### Request Routing Flow

When multiple trajectories run concurrently, each trajectory's agent sends inference requests. The `AsyncLLMServerManager` routes these requests to available vLLM engines:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          Concurrent Trajectories                                 │
│                                                                                  │
│   Trajectory 0        Trajectory 1        Trajectory 2        Trajectory N      │
│       │                   │                   │                   │             │
│       │ generate()        │ generate()        │ generate()        │ generate()  │
│       ▼                   ▼                   ▼                   ▼             │
└───────┼───────────────────┼───────────────────┼───────────────────┼─────────────┘
        │                   │                   │                   │
        └───────────────────┴─────────┬─────────┴───────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         AsyncLLMServerManager                                    │
│                                                                                  │
│   generate(request_id, prompt_ids, sampling_params):                            │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │  1. Receive request with unique request_id                              │   │
│   │  2. Select available vLLM server (round-robin or load-based)           │   │
│   │  3. Forward request to selected server                                  │   │
│   │  4. Server processes request asynchronously                             │   │
│   │  5. Return response when ready                                          │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│   Request Queue / Router:                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                                                                         │   │
│   │   Request 0 ──┐                                                         │   │
│   │   Request 1 ──┼──► Router ──┬──► vLLM Server 0 (processing Request 0)  │   │
│   │   Request 2 ──┤             ├──► vLLM Server 1 (processing Request 1)  │   │
│   │   Request 3 ──┘             └──► vLLM Server 2 (processing Request 2)  │   │
│   │                                   (Request 3 waits for available server)│   │
│   │                                                                         │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         vLLM Server (Ray Actor)                                  │
│                                                                                  │
│   SkyAgentAsyncvLLMServer:                                                      │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                                                                         │   │
│   │   Components:                                                           │   │
│   │   - vLLM AsyncLLMEngine (manages GPU inference)                        │   │
│   │   - Request queue (handles concurrent requests)                        │   │
│   │   - KV cache (stores attention states)                                 │   │
│   │                                                                         │   │
│   │   generate(prompt_ids, sampling_params, request_id):                   │   │
│   │   1. Create TokensPrompt from prompt_ids                               │   │
│   │   2. Submit to AsyncLLMEngine                                          │   │
│   │   3. Engine batches requests for efficient GPU utilization             │   │
│   │   4. Return generated text + metadata                                  │   │
│   │                                                                         │   │
│   │   Output:                                                               │   │
│   │   - response_str: Generated text                                       │   │
│   │   - meta_info: {output_tokens, finish_reason, logprobs}               │   │
│   │                                                                         │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### Sequence Diagram: Single Request

```
┌──────────┐    ┌───────────────┐    ┌─────────────────────┐    ┌─────────────┐
│  Agent   │    │  VeRLBackend  │    │AsyncLLMServerManager│    │ vLLM Server │
└────┬─────┘    └───────┬───────┘    └──────────┬──────────┘    └──────┬──────┘
     │                  │                       │                      │
     │ async_generate_ids(input_ids, params)    │                      │
     │─────────────────►│                       │                      │
     │                  │                       │                      │
     │                  │ generate(request_id,  │                      │
     │                  │   prompt_ids, params) │                      │
     │                  │──────────────────────►│                      │
     │                  │                       │                      │
     │                  │                       │ select_server()      │
     │                  │                       │─────────┐            │
     │                  │                       │◄────────┘            │
     │                  │                       │                      │
     │                  │                       │ generate.remote()    │
     │                  │                       │─────────────────────►│
     │                  │                       │                      │
     │                  │                       │      (async GPU      │
     │                  │                       │       inference)     │
     │                  │                       │                      │
     │                  │                       │◄─────────────────────│
     │                  │                       │ (response, meta_info)│
     │                  │                       │                      │
     │                  │◄──────────────────────│                      │
     │                  │                       │                      │
     │◄─────────────────│                       │                      │
     │ (response_str, meta_info)                │                      │
     │                  │                       │                      │
```

#### Key Features

| Feature | Description |
|---------|-------------|
| **Data Parallelism** | Multiple vLLM servers (DP ranks) handle requests in parallel |
| **Ray Actors** | Each vLLM server runs as an independent Ray actor on dedicated GPU |
| **Async Generation** | Non-blocking inference allows concurrent trajectory execution |
| **Request Routing** | Manager routes requests to available servers |
| **GPU Isolation** | Each server owns specific GPU(s), FSDP training uses separate GPUs |
| **Sleep/Wake** | Servers can sleep to free GPU memory during training phase |

#### GPU Allocation Example

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          GPU Allocation (4 GPU setup)                            │
│                                                                                  │
│   GPU 0          GPU 1          GPU 2          GPU 3                            │
│   ┌────┐         ┌────┐         ┌────┐         ┌────┐                           │
│   │FSDP│         │FSDP│         │vLLM│         │vLLM│                           │
│   │    │         │    │         │    │         │    │                           │
│   │Rank│         │Rank│         │DP  │         │DP  │                           │
│   │ 0  │         │ 1  │         │Rank│         │Rank│                           │
│   │    │         │    │         │ 0  │         │ 1  │                           │
│   └────┘         └────┘         └────┘         └────┘                           │
│      │              │              │              │                              │
│      └──────┬───────┘              └──────┬───────┘                              │
│             │                             │                                      │
│      Training Phase                Rollout Phase                                 │
│   (PPO update on model)      (Inference for trajectories)                       │
│                                                                                  │
│   n_gpus_per_node = 2        rollout_dp_size = 2                                │
│   (FSDP training)            (vLLM inference)                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### Code Flow

```python
# 1. SkyAgentLoopManager creates vLLM servers
self.rollout_dp_size = 2  # Number of vLLM servers
self.async_llm_servers = [
    SkyAgentAsyncvLLMServer.remote(config, dp_size=2, dp_rank=0, ...),
    SkyAgentAsyncvLLMServer.remote(config, dp_size=2, dp_rank=1, ...),
]

# 2. AsyncLLMServerManager wraps the servers
self.server_manager = AsyncLLMServerManager(config, self.async_llm_servers)

# 3. VeRLBackend provides unified interface
class VeRLBackend(AsyncInferBackend):
    async def async_generate_ids(self, input_ids, sampling_params, request_id):
        # Routes to AsyncLLMServerManager
        response, meta = await self.infer_engine.generate(
            request_id=request_id,
            prompt_ids=input_ids,
            sampling_params=sampling_params,
        )
        return response, meta

# 4. Agent calls inference
response, meta = await self.infer_engine.async_generate_ids(
    input_ids=prompt_tokens,
    sampling_params={"temperature": 1.0, "max_tokens": 4096},
    request_id=f"traj_{instance_id}_{step}",
)
```

---

### 3.6 Dispatcher: Managing Trajectories and Environment Pool

The dispatcher is responsible for executing multiple trajectories in parallel while managing a limited pool of environments. This section explains how `async_fix_pool` dispatcher maps trajectories to environments.

#### Problem: More Trajectories Than Environments

In a typical training setup, we may have:
- **8 trajectories** to execute (e.g., 4 instances × 2 trajectories each)
- **4 environments** available (e.g., 4 Docker containers)

The dispatcher must efficiently schedule trajectories to reuse environments.

#### async_fix_pool Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AgentRunner                                         │
│                                                                                  │
│   trajectories = {                                                              │
│     "inst_0": {"traj_0": Trajectory, "traj_1": Trajectory},                    │
│     "inst_1": {"traj_0": Trajectory, "traj_1": Trajectory},                    │
│     "inst_2": {"traj_0": Trajectory, "traj_1": Trajectory},                    │
│     "inst_3": {"traj_0": Trajectory, "traj_1": Trajectory},                    │
│   }                                                                             │
│   Total: 8 trajectories                                                         │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         │ dispatch to async_fix_pool
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         async_fix_pool Dispatcher                                │
│                                                                                  │
│   Configuration:                                                                │
│   - max_parallel_agents: 4 (matches environment pool size)                     │
│   - env_pool: [Env_0, Env_1, Env_2, Env_3]                                    │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                          Work Queue                                     │   │
│   │                                                                         │   │
│   │   ┌───────────────────────────────────────────────────────────────┐    │   │
│   │   │ (inst_0,traj_0) (inst_0,traj_1) (inst_1,traj_0) (inst_1,traj_1)│    │   │
│   │   │ (inst_2,traj_0) (inst_2,traj_1) (inst_3,traj_0) (inst_3,traj_1)│    │   │
│   │   └───────────────────────────────────────────────────────────────┘    │   │
│   │                                                                         │   │
│   │   8 trajectories waiting to be processed                               │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                         Worker Pool (4 workers)                         │   │
│   │                                                                         │   │
│   │   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐           │   │
│   │   │ Worker 0 │   │ Worker 1 │   │ Worker 2 │   │ Worker 3 │           │   │
│   │   │          │   │          │   │          │   │          │           │   │
│   │   │ Env_0    │   │ Env_1    │   │ Env_2    │   │ Env_3    │           │   │
│   │   │ assigned │   │ assigned │   │ assigned │   │ assigned │           │   │
│   │   └──────────┘   └──────────┘   └──────────┘   └──────────┘           │   │
│   │                                                                         │   │
│   │   Each worker owns one environment from the pool                       │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### Execution Timeline: 8 Trajectories, 4 Environments

```
Time ──────────────────────────────────────────────────────────────────────────────►

Wave 1: First 4 trajectories claim environments
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                  │
│   Env_0          Env_1          Env_2          Env_3                            │
│   ┌────┐         ┌────┐         ┌────┐         ┌────┐                           │
│   │inst│         │inst│         │inst│         │inst│                           │
│   │ 0  │         │ 0  │         │ 1  │         │ 1  │                           │
│   │traj│         │traj│         │traj│         │traj│                           │
│   │ 0  │         │ 1  │         │ 0  │         │ 1  │                           │
│   └────┘         └────┘         └────┘         └────┘                           │
│      │              │              │              │                              │
│      ▼              ▼              ▼              ▼                              │
│   [init]         [init]         [init]         [init]                           │
│   [run ...]      [run ...]      [run ...]      [run ...]                        │
│   [eval]         [eval]         [eval]         [eval]                           │
│      │              │              │              │                              │
│      ▼              ▼              ▼              ▼                              │
│   DONE ─┐        DONE ─┐        DONE ─┐        DONE ─┐                          │
│         │              │              │              │                           │
└─────────┼──────────────┼──────────────┼──────────────┼───────────────────────────┘
          │              │              │              │
          │   Environments released back to pool       │
          ▼              ▼              ▼              ▼

Wave 2: Remaining 4 trajectories claim freed environments
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                  │
│   Env_0          Env_1          Env_2          Env_3                            │
│   ┌────┐         ┌────┐         ┌────┐         ┌────┐                           │
│   │inst│         │inst│         │inst│         │inst│                           │
│   │ 2  │         │ 2  │         │ 3  │         │ 3  │                           │
│   │traj│         │traj│         │traj│         │traj│                           │
│   │ 0  │         │ 1  │         │ 0  │         │ 1  │                           │
│   └────┘         └────┘         └────┘         └────┘                           │
│      │              │              │              │                              │
│      ▼              ▼              ▼              ▼                              │
│   [init]         [init]         [init]         [init]                           │
│   [run ...]      [run ...]      [run ...]      [run ...]                        │
│   [eval]         [eval]         [eval]         [eval]                           │
│      │              │              │              │                              │
│      ▼              ▼              ▼              ▼                              │
│   DONE           DONE           DONE           DONE                             │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

All 8 trajectories completed using only 4 environments
```

#### Detailed Worker Logic

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Worker Execution Loop                                  │
│                                                                                  │
│   async def worker(worker_id, env, work_queue, results):                        │
│       while True:                                                               │
│           # 1. Get next trajectory from queue                                   │
│           trajectory = await work_queue.get()                                   │
│           if trajectory is None:  # Poison pill                                 │
│               break                                                             │
│                                                                                  │
│           # 2. Assign environment to trajectory                                 │
│           trajectory.env_handle = env                                           │
│                                                                                  │
│           # 3. Execute full trajectory lifecycle                                │
│           ┌─────────────────────────────────────────────────────────────────┐   │
│           │  await trajectory.initialize_trajectory()                       │   │
│           │    - env.reset(task_config)                                     │   │
│           │    - Get initial screenshot                                     │   │
│           │    - Load task instruction                                      │   │
│           │                                                                 │   │
│           │  await trajectory.generate_trajectory()                         │   │
│           │    - Agent loop: inference → action → observation              │   │
│           │    - Multiple steps until done or max_iterations               │   │
│           │                                                                 │   │
│           │  await trajectory.evaluate_trajectory()                         │   │
│           │    - Check task success                                         │   │
│           │    - Compute reward                                             │   │
│           └─────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│           # 4. Store result (env automatically available for next trajectory)  │
│           results.append(trajectory.result)                                     │
│                                                                                  │
│           # 5. Loop back to get next trajectory (env reused)                   │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### Sequence Diagram: Environment Reuse

```
┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
│ Work Queue │   │  Worker 0  │   │   Env_0    │   │  Results   │
└─────┬──────┘   └─────┬──────┘   └─────┬──────┘   └─────┬──────┘
      │                │                │                │
      │ get()          │                │                │
      │───────────────►│                │                │
      │ (inst_0,traj_0)│                │                │
      │                │                │                │
      │                │  reset()       │                │
      │                │───────────────►│                │
      │                │                │                │
      │                │  [run trajectory with Env_0]   │
      │                │◄──────────────►│                │
      │                │                │                │
      │                │                │   append()     │
      │                │────────────────┼───────────────►│
      │                │                │  (traj_0 result)
      │                │                │                │
      │ get()          │                │                │
      │───────────────►│ (Env_0 now free, worker loops) │
      │ (inst_2,traj_0)│                │                │
      │                │                │                │
      │                │  reset()       │                │
      │                │───────────────►│ (reuse Env_0)  │
      │                │                │                │
      │                │  [run trajectory with Env_0]   │
      │                │◄──────────────►│                │
      │                │                │                │
      │                │                │   append()     │
      │                │────────────────┼───────────────►│
      │                │                │  (traj_2 result)
      │                │                │                │
```

#### Key Configuration Parameters

```yaml
# Example: verl_android_test.yaml
dispatcher:
  type: async_fix_pool
  max_parallel_agents: 4    # Number of concurrent workers (= env pool size)

env:
  pool_size: 4              # Number of Docker containers to create
  docker_image: androidworld:v8
  snapshot: clean           # Reset strategy for env reuse

generator:
  num_trajectories: 2       # Trajectories per instance
  # With batch_size=4 instances: 4 × 2 = 8 total trajectories
```

#### Comparison: async_fix_pool vs async_pipeline

| Aspect | async_fix_pool | async_pipeline |
|--------|----------------|----------------|
| **Env Binding** | Worker owns env for duration | Env assigned per phase |
| **Best For** | Expensive env setup (Docker) | Cheap env setup |
| **Parallelism** | Limited by env pool size | Limited by queue capacity |
| **Env Reuse** | Same env processes multiple trajectories | May vary |
| **Complexity** | Simpler (single loop) | Three-stage pipeline |

#### Code Implementation

```python
# Simplified async_fix_pool dispatcher logic
async def async_fix_pool_dispatcher(
    trajectories: List[BaseTrajectory],
    env_pool: List[RuntimeClient],
    max_parallel: int,
):
    work_queue = asyncio.Queue()
    results = []

    # Fill work queue with all trajectories
    for traj in trajectories:
        await work_queue.put(traj)

    # Add poison pills to signal workers to stop
    for _ in range(max_parallel):
        await work_queue.put(None)

    # Create workers, each with assigned environment
    async def worker(worker_id: int, env: RuntimeClient):
        while True:
            traj = await work_queue.get()
            if traj is None:
                break

            # Assign env to trajectory
            traj.env_handle = env

            # Execute trajectory lifecycle
            await traj.initialize_trajectory()
            await traj.generate_trajectory()
            await traj.evaluate_trajectory()

            results.append(traj.result)

    # Launch workers in parallel
    workers = [
        worker(i, env_pool[i])
        for i in range(max_parallel)
    ]
    await asyncio.gather(*workers)

    return results
```

---

## 4. Core Components

### 4.1 Agent System

The agent system consists of two main classes that work together:

#### BaseTrajectory

Location: `skyrl_agent/agents/base.py`

`BaseTrajectory` is the abstract base class for all trajectory implementations. Each trajectory represents a single agent episode from initialization to completion.

```python
class BaseTrajectory(ABC):
    def __init__(
        self,
        cfg: TrajectoryConfig,      # Configuration dataclass
        data: Dict[str, Any],       # Instance data
        infer_engine: AsyncInferBackend,  # LLM backend
        tokenizer: AutoTokenizer,   # Tokenizer
        task: BaseTask,             # Task reference
        val_mode: bool = False,     # Validation mode
    ) -> None:
        ...

    @abstractmethod
    async def initialize_trajectory(self):
        """Setup agent and environment"""
        pass

    @abstractmethod
    async def generate_trajectory(self):
        """Run the agent loop"""
        pass

    @abstractmethod
    async def evaluate_trajectory(self):
        """Evaluate and compute reward"""
        pass
```

#### AgentRunner

Location: `skyrl_agent/agents/base.py`

`AgentRunner` manages batches of trajectories and coordinates with the dispatcher for parallel execution.

Key responsibilities:
- Load configuration from YAML task files
- Create trajectory instances for each (instance, trajectory_id) pair
- Dispatch trajectories via the selected dispatcher
- Post-process results into training tensors

```python
class AgentRunner:
    @classmethod
    def from_task(cls, task: str, infer_engine: Any, tokenizer: Any):
        """Create runner from task YAML path or registered name"""
        ...

    async def run(self, input_batch: Any, val_mode: bool = False) -> Any:
        """Main entry point for trajectory generation"""
        ...
```

### 4.2 Task System

Location: `skyrl_agent/tasks/base.py`

`BaseTask` defines the interface for task-specific runtime management and evaluation.

```python
class BaseTask(ABC):
    @classmethod
    @abstractmethod
    async def initialize_runtime(cls, *args, **kwargs) -> Any:
        """Initialize task runtime (e.g., Docker containers)"""
        pass

    @classmethod
    @abstractmethod
    def get_instruction(cls, *args, **kwargs) -> List[Dict[str, str]]:
        """Get initial instruction in OpenAI messages format"""
        pass

    @classmethod
    @abstractmethod
    def complete_runtime(cls, *args, **kwargs) -> Dict[str, Any]:
        """Finalize runtime and extract artifacts"""
        pass

    @classmethod
    @abstractmethod
    async def evaluate_result(cls, *args, **kwargs) -> bool:
        """Evaluate trajectory result"""
        pass
```

### 4.3 Tool System

Location: `skyrl_agent/tools/base.py`

Tools provide the interface between agents and their environment. Each tool is registered via decorator and implements a standard interface.

```python
# Registration
@register_tool("my_tool")
class MyTool(BaseTool):
    name = "my_tool"
    description = "Description of what the tool does"
    parameters = {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"]
    }

    def call(self, params: Union[str, dict], **kwargs) -> Union[str, dict]:
        """Execute the tool action"""
        ...
```

Available tools are stored in `TOOL_REGISTRY` and can be enabled via YAML configuration:

```yaml
tools:
  enable_android_env: true
  enable_search: false
```

### 4.4 Dispatcher System

Location: `skyrl_agent/dispatcher/dispatchers.py`

Dispatchers control how trajectories are executed in parallel. Two main strategies are available:

#### async_pipeline

Producer-consumer pipelining with three queues (init → run → eval):

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  Init    │────>│   Run    │────>│   Eval   │
│  Queue   │     │  Queue   │     │  Queue   │
└──────────┘     └──────────┘     └──────────┘
     │                │                │
     ▼                ▼                ▼
  Workers          Workers          Workers
```

Best for: Tasks where init/run/eval have different resource requirements.

#### async_fix_pool

Fixed pool of pre-initialized environments with worker reuse:

```
┌─────────────────────────────────────────┐
│           Environment Pool              │
│  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐    │
│  │Env 0│  │Env 1│  │Env 2│  │Env 3│    │
│  └──┬──┘  └──┬──┘  └──┬──┘  └──┬──┘    │
└─────┼────────┼────────┼────────┼────────┘
      │        │        │        │
      ▼        ▼        ▼        ▼
   Worker   Worker   Worker   Worker
      │        │        │        │
      └────────┴────────┴────────┘
                   │
            Work Queue (trajectories)
```

Best for: Tasks with expensive environment setup (e.g., Docker containers).

### 4.5 Backend System

Location: `skyrl_agent/integrations/base.py`

The backend system provides a unified interface for different training/inference backends.

```python
class AsyncInferBackend(ABC):
    @abstractmethod
    async def async_generate_prompts(
        self, prompts: Any, sampling_params: Any, **kwargs
    ) -> List[str]:
        """Generate from text prompts"""
        pass

    @abstractmethod
    async def async_generate_ids(
        self, input_ids: Any, sampling_params: Any, **kwargs
    ) -> List[str]:
        """Generate from token IDs"""
        pass
```

Backends are registered via `BackendSpec`:

```python
spec = BackendSpec(
    infer_backend_cls=MyBackend,
    generator_output_cls=MyGeneratorOutput,
    generator_input_cls=MyGeneratorInput,
)
register_backend("my_backend", spec)
```

### 4.6 Configuration System

Location: `skyrl_agent/config/configuration_utils.py`

#### TrajectoryConfig

Dataclass containing all configuration for a single trajectory:

```python
@dataclass
class TrajectoryConfig:
    instance_id: int              # Unique instance identifier
    trajectory_id: int            # Trajectory index
    max_prompt_length: int = 1024 # Token limit
    sampling_params: Optional[Any] = None  # LLM sampling config
    vision_is_active: bool = False         # Enable vision
    qwen3_enable_thinking: bool = True     # Qwen3 thinking mode
    max_iterations: int = 5                # Max agent steps
    tools: Optional[list] = None           # Enabled tools
    agent_cls: str = "skyrl_agent.agents.react.ReActAgent"
    profile_tools: bool = False            # Tool profiling
    debug_log: bool = False                # Debug logging
```

#### YAML Task Configuration

Tasks are defined via YAML files that specify all components:

```yaml
# Example: verl_android_test.yaml
agent_cls: skyrl_agent.agents.android.AndroidAgent
task: skyrl_agent.tasks.android.android_task.AndroidTask

tools:
  enable_android_env: true

data:
  instance_key: instance
  instance_id_key: instance.instance_id

env:
  pool_size: 2
  docker_image: androidworld:v8

generator:
  infer_backend: verl
  num_trajectories: 2
  max_iterations: 30
  sampling_params:
    temperature: 1.0
    max_tokens: 4096

dispatcher:
  type: async_fix_pool
  max_parallel_agents: 2
```

---

## 5. Data Flow

### Complete Training Data Flow

This section traces data from input to training update:

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. DATA LOADING                                                  │
│    Dataset (JSONL) → List[Dict] instances                       │
│    Each instance contains task-specific data                     │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. BATCH PREPARATION                                             │
│    AgentRunner._get_data(content) extracts:                     │
│    - instance: Task payload                                      │
│    - instance_id: Unique identifier                              │
│    - data_source: Origin marker                                  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. TRAJECTORY INITIALIZATION                                     │
│    For each (instance_id, trajectory_id):                       │
│    - Create TrajectoryConfig with sampling params                │
│    - Instantiate BaseTrajectory subclass                        │
│    - Store in self.trajectories[instance_id][trajectory_id]     │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. DISPATCHER EXECUTION                                          │
│    Dispatcher calls three phases per trajectory:                 │
│                                                                  │
│    initialize_trajectory():                                      │
│    - Task.get_instruction() → initial messages                   │
│    - Setup agent state                                           │
│                                                                  │
│    generate_trajectory():                                        │
│    - Agent loop: inference → action → observation               │
│    - Collect transitions for training                            │
│                                                                  │
│    evaluate_trajectory():                                        │
│    - Task.evaluate_result() → reward                            │
│    - Store in trajectory.result                                  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. POST-PROCESSING                                               │
│    AgentRunner._post_process_results() converts:                │
│                                                                  │
│    TrajectoryResult → Training Tensors:                         │
│    - prompt_token_ids: List[List[int]]                          │
│    - response_ids: List[List[int]]                              │
│    - rewards: List[float]                                        │
│    - loss_masks: List[List[int]]                                │
│    - rollout_logprobs: List[List[float]]                        │
│                                                                  │
│    Compute rollout_metrics:                                      │
│    - avg_turn_assistant, finish_tool_ratio, etc.                │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. TRAINING UPDATE                                               │
│    VERL Trainer receives GeneratorOutput:                       │
│    - Compute advantages (GRPO/GAE)                               │
│    - PPO policy update                                           │
│    - Log metrics and checkpoint                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Single Trajectory Execution Detail

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRAJECTORY LIFECYCLE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  INITIALIZE:                                                     │
│  ───────────                                                     │
│  1. Load task instruction via Task.get_instruction()            │
│  2. Initialize agent with instruction messages                   │
│  3. Capture initial screenshot (if vision task)                  │
│  4. Set step_count = 0, is_done = False                         │
│                                                                  │
│  GENERATE (Agent Loop):                                          │
│  ──────────────────────                                          │
│  while not is_done and step_count < max_iterations:             │
│    │                                                             │
│    │  ┌─────────────────────────────────────────────┐           │
│    │  │ 1. Format messages for LLM                  │           │
│    │  │    - System prompt + conversation history    │           │
│    │  │    - Include images if vision_is_active     │           │
│    │  └─────────────────────────────────────────────┘           │
│    │                         │                                   │
│    │                         ▼                                   │
│    │  ┌─────────────────────────────────────────────┐           │
│    │  │ 2. LLM Inference via AsyncInferBackend      │           │
│    │  │    - async_generate_prompts(messages, params)│           │
│    │  │    - Returns: assistant response text       │           │
│    │  └─────────────────────────────────────────────┘           │
│    │                         │                                   │
│    │                         ▼                                   │
│    │  ┌─────────────────────────────────────────────┐           │
│    │  │ 3. Parse Action from response               │           │
│    │  │    - Extract tool name and parameters       │           │
│    │  │    - Handle finish/answer actions           │           │
│    │  └─────────────────────────────────────────────┘           │
│    │                         │                                   │
│    │                         ▼                                   │
│    │  ┌─────────────────────────────────────────────┐           │
│    │  │ 4. Execute Tool via BaseTool.call()         │           │
│    │  │    - Pass params to environment             │           │
│    │  │    - Receive observation (screenshot, etc.) │           │
│    │  └─────────────────────────────────────────────┘           │
│    │                         │                                   │
│    │                         ▼                                   │
│    │  ┌─────────────────────────────────────────────┐           │
│    │  │ 5. Update State                             │           │
│    │  │    - Append assistant message to history    │           │
│    │  │    - Append observation to history          │           │
│    │  │    - Increment step_count                   │           │
│    │  │    - Check termination conditions           │           │
│    │  └─────────────────────────────────────────────┘           │
│    │                                                             │
│    └────────────────── Loop ─────────────────────────           │
│                                                                  │
│  EVALUATE:                                                       │
│  ─────────                                                       │
│  1. Call Task.evaluate_result() with final state                │
│  2. Compute reward (True/False or float)                        │
│  3. Set finish_reason based on termination cause                │
│  4. Store result in trajectory.result                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Appendix: Directory Structure

```
skyrl-agent/
├── skyrl_agent/
│   ├── agents/
│   │   ├── base.py              # BaseTrajectory, AgentRunner
│   │   ├── mapping.py           # Agent registries
│   │   ├── react/               # ReAct agent implementation
│   │   ├── oh_codeact/          # CodeAct agent implementation
│   │   └── android/             # Android agent implementation
│   │
│   ├── tasks/
│   │   ├── base.py              # BaseTask interface
│   │   ├── android/             # AndroidTask
│   │   ├── swebench/            # SWE-Bench tasks
│   │   └── verifiers/           # Result verification
│   │
│   ├── tools/
│   │   ├── base.py              # BaseTool, TOOL_REGISTRY
│   │   ├── android_env.py       # Android environment tool
│   │   ├── search_engine.py     # Search tool
│   │   └── ...
│   │
│   ├── integrations/
│   │   ├── base.py              # AsyncInferBackend, BACKEND_REGISTRY
│   │   ├── verl/                # VERL backend
│   │   ├── skyrl_train/         # SkyRL-Train backend
│   │   └── tinker/              # Tinker backend
│   │
│   ├── dispatcher/
│   │   └── dispatchers.py       # DISPATCHER_REGISTRY
│   │
│   ├── config/
│   │   └── configuration_utils.py  # TrajectoryConfig
│   │
│   └── runtime/
│       └── android/             # Container management
│
├── examples/
│   └── run_verl/                # VERL training examples
│       ├── verl_android.yaml
│       └── verl_android.sh
│
└── docs/
    └── SKYRL_AGENT_FRAMEWORK.md # This document
```
