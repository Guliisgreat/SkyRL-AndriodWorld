# SkyRL-AndroidWorld Code Structure Reference

This document describes the recommended code structure for integrating AndroidWorld into the SkyRL framework.

## Overview

SkyRL-AndroidWorld is a monorepo with multiple packages:

| Package | Purpose |
|---------|---------|
| `skyrl-agent` | Agent framework (agents, tasks, tools, runtime environments, training integrations) |
| `skyrl-train` | RL training framework (trainer, workers, generators, inference engines) |
| `skyrl-tx` | Tinker-like REST API (experimental) |

AndroidWorld adds a new environment integration for training RL agents on Android device tasks.

---

## Repository Structure

```
SkyRL-AndroidWorld/
│
├── skyrl-agent/                          # Agent framework package
│   ├── pyproject.toml
│   ├── README.md
│   ├── examples/
│   │   ├── run_verl/                     # Existing VeRL examples
│   │   ├── run_skyrl/                    # Existing SkyRL examples
│   │   └── run_android/                  # NEW: Android examples
│   │       └── container_manager_demo.py
│   │
│   └── skyrl_agent/
│       ├── __init__.py
│       │
│       ├── agents/                       # Agent implementations
│       │   ├── __init__.py
│       │   ├── base.py                   # Base Agent class
│       │   ├── react/                    # ReAct agent
│       │   ├── oh_codeact/               # CodeAct agent
│       │   └── android/                  # NEW: Android agent
│       │       ├── __init__.py
│       │       ├── android_agent.py
│       │       └── android_runner.py
│       │
│       ├── tasks/                        # Task definitions
│       │   ├── __init__.py
│       │   ├── base.py                   # Base Task class
│       │   ├── swebench/                 # SWE-Bench tasks
│       │   ├── web_research_task.py
│       │   └── android/                  # NEW: Android tasks
│       │       ├── __init__.py
│       │       └── android_task.py
│       │
│       ├── tools/                        # Tool implementations
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── search.py
│       │   ├── web_browser.py
│       │   └── android/                  # NEW: Android tools (if needed)
│       │       └── __init__.py
│       │
│       ├── runtime/                      # NEW: Environment runtimes
│       │   ├── __init__.py
│       │   └── android/                  # Android runtime
│       │       ├── __init__.py
│       │       ├── container_manager.py  # Docker container pool management
│       │       ├── runtime_client.py     # HTTP client for FastAPI server
│       │       ├── environment.py        # AndroidWorld environment wrapper
│       │       └── config.py             # Configuration classes
│       │
│       ├── integrations/                 # Training backend integrations
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── verl/                     # VeRL integration
│       │   ├── skyrl_train/              # SkyRL-train integration
│       │   └── tinker/                   # Tinker integration
│       │
│       ├── dispatcher/                   # Async dispatching
│       ├── functional/                   # Utilities
│       └── config/                       # Configuration utilities
│
├── skyrl-train/                          # Training framework package
│   ├── pyproject.toml
│   ├── README.md
│   │
│   └── skyrl_train/                      # Core training code
│       ├── trainer.py
│       ├── workers/
│       ├── generators/
│       └── inference_engines/
│
├── skyrl-tx/                             # Tinker-like API (unchanged)
│   └── ...
│
├── docker/                               # Docker configurations
│   ├── Dockerfile                        # Training infrastructure
│   ├── Dockerfile.megatron
│   ├── Dockerfile.ray244
│   └── android/                          # NEW: Android container
│       ├── Dockerfile                    # AndroidWorld image build
│       ├── entrypoint.sh                 # Container startup script
│       ├── requirements.txt              # Python dependencies
│       └── server/                       # FastAPI server (runs in container)
│           ├── __init__.py
│           ├── server.py                 # FastAPI endpoints
│           ├── env.py                    # AndroidWorldEnv class
│           └── logger_config.py          # Logging configuration
│
├── configs/                              # NEW: Configuration files
│   └── android/
│       ├── default.yaml                  # Default Android settings
│       └── avd/
│           └── AWAvd.ini                 # AVD configuration
│
└── docs/
    ├── R2E_GYM_VERL_TRAINING_SETUP.md
    └── code structure reference.md       # This document
```

---

## Component Descriptions

### 1. Agent Layer (`skyrl-agent/skyrl_agent/agents/android/`)

The Android agent handles interaction with Android devices.

```python
# android_agent.py
class AndroidAgent(BaseAgent):
    """Agent for AndroidWorld tasks."""
    
    def act(self, observation: Dict) -> Dict:
        """Generate action from observation (screenshot + task)."""
        # Process image and task description
        # Generate action using LLM
        pass
```

### 2. Task Layer (`skyrl-agent/skyrl_agent/tasks/android/`)

Android task definitions from the AndroidWorld benchmark.

```python
# android_task.py
class AndroidTask(BaseTask):
    """Task definition for AndroidWorld."""
    
    def get_goal(self) -> str:
        """Return the task goal description."""
        pass
    
    def evaluate(self, trajectory) -> float:
        """Evaluate if the task was completed successfully."""
        pass
```

### 3. Runtime Layer (`skyrl-agent/skyrl_agent/runtime/android/`)

Docker container management and runtime communication. This layer provides the environment for agents to interact with.

#### Container Manager

```python
# container_manager.py
class ContainerManager:
    """Manages pool of Docker containers running Android emulators."""
    
    async def create_pool(self, size: int, **kwargs) -> List[ContainerInstance]:
        """Create a pool of containers with Android emulators."""
        pass
    
    async def allocate_container(self) -> ContainerInstance:
        """Get an available container from the pool."""
        pass
    
    async def release_container(self, container: ContainerInstance):
        """Return container to the pool after use."""
        pass
    
    async def cleanup(self):
        """Stop and remove all containers."""
        pass
```

#### Runtime Client

```python
# runtime_client.py
class RuntimeClient:
    """HTTP client for communicating with FastAPI server in container."""
    
    async def reset(self, options: Dict) -> Tuple[Observation, Info]:
        """Reset environment and start new task."""
        pass
    
    async def step(self, action: Dict) -> Tuple[Obs, Reward, Done, Truncated, Info]:
        """Execute action and get result."""
        pass
    
    async def health_check(self) -> bool:
        """Check if container is healthy."""
        pass
```

### 4. Docker Container (`docker/android/`)

The Docker container runs inside it:
- Android emulator (QEMU-based)
- FastAPI server exposing HTTP endpoints
- AndroidWorldEnv that controls the emulator

#### FastAPI Server (`server/server.py`)

```python
@app.post("/reset")
async def reset(env: Env, data: ResetInput):
    """Reset environment to new task."""
    observation, info = env.reset(seed=data.seed, options=data.options)
    return {"observation": observation, "info": info}

@app.post("/step")
async def step(env: Env, data: StepInput):
    """Execute action in environment."""
    obs, reward, terminated, truncated, info = env.step(action=data.action)
    return {"observation": obs, "reward": reward, "done": terminated or truncated}

@app.get("/health")
async def health(env: Env):
    """Health check endpoint."""
    return {"status": "success"}
```

#### AndroidWorldEnv (`server/env.py`)

The environment class that controls the Android emulator. **Configurable via environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_SNAPSHOT` | `true` | Use snapshot or cold boot |
| `GPU_MODE` | `auto` | GPU emulation mode |
| `EMULATOR_BOOT_WAIT` | `30` | Seconds to wait for boot |

```python
def _start_emulator(self):
    # Read config from environment
    use_snapshot = os.getenv("USE_SNAPSHOT", "true") == "true"
    gpu_mode = os.getenv("GPU_MODE", "auto")
    boot_wait = int(os.getenv("EMULATOR_BOOT_WAIT", "30"))
    
    # Build command based on config
    if use_snapshot:
        snapshot_arg = f"-snapshot {self.snapshot}"
    else:
        snapshot_arg = "-no-snapshot"
    
    command = f"emulator -avd {self.avd_name} {snapshot_arg} -gpu {gpu_mode} ..."
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        HOST MACHINE                                 │
│                                                                     │
│   skyrl-agent/skyrl_agent/                                          │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  agents/android/              runtime/android/              │  │
│   │  • AndroidAgent               • ContainerManager            │  │
│   │  • AndroidRunner        ────► • RuntimeClient               │  │
│   │                               • Environment                 │  │
│   │  tasks/android/               │                             │  │
│   │  • AndroidTask                │                             │  │
│   └───────────────────────────────┼─────────────────────────────┘  │
│                                   │ HTTP                           │
│                                   │                                │
├───────────────────────────────────┼────────────────────────────────┤
│                      DOCKER CONTAINER                              │
│   ┌───────────────────────────────▼──────────────────────────────┐ │
│   │  docker/android/server/                                      │ │
│   │  ┌─────────────────┐         ┌─────────────────────────────┐│ │
│   │  │   FastAPI       │────────►│   AndroidWorldEnv           ││ │
│   │  │   server.py     │         │   (env.py)                  ││ │
│   │  │                 │         │   • Configurable via env    ││ │
│   │  │   /reset        │         │   • Controls emulator       ││ │
│   │  │   /step         │         └─────────────┬───────────────┘│ │
│   │  │   /health       │                       │ gRPC            │ │
│   │  └─────────────────┘         ┌─────────────▼───────────────┐│ │
│   │                              │   Android Emulator (QEMU)   ││ │
│   │                              │   AVD: AWAvd                ││ │
│   │                              └─────────────────────────────┘│ │
│   └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Configuration

### Default Configuration (`configs/android/default.yaml`)

```yaml
docker:
  image: androidworld:v8

emulator:
  avd_name: AWAvd
  use_snapshot: false           # Cold boot for stability
  gpu_mode: swiftshader_indirect
  boot_wait_seconds: 90

container:
  pool_size: 4
  health_check_interval: 30
  server_timeout: 600
  retry_interval: 10
```

### Using Configuration in ContainerManager

```python
from skyrl_agent.runtime.android import ContainerManager

config = load_config("configs/android/default.yaml")

manager = ContainerManager(
    docker_image=config.docker.image,
    pool_size=config.container.pool_size,
)

# Config passed as environment variables to container
await manager.create_pool(
    environment={
        "USE_SNAPSHOT": str(config.emulator.use_snapshot).lower(),
        "GPU_MODE": config.emulator.gpu_mode,
        "EMULATOR_BOOT_WAIT": str(config.emulator.boot_wait_seconds),
    }
)
```

---

## Migration from aw_g Repository

| Source (`aw_g/`) | Destination | Action |
|------------------|-------------|--------|
| `skyrl_agent/agents/android/` | `skyrl-agent/skyrl_agent/agents/android/` | Move |
| `skyrl_agent/tasks/android/` | `skyrl-agent/skyrl_agent/tasks/android/` | Move |
| `skyrl_agent/runtime/androidworld/container_manager.py` | `skyrl-agent/skyrl_agent/runtime/android/container_manager.py` | Move |
| `skyrl_agent/runtime/androidworld/runtime_client.py` | `skyrl-agent/skyrl_agent/runtime/android/runtime_client.py` | Move |
| `docker_env/RL4AndroidWorld/server/` | `docker/android/server/` | Move |
| `docker_env/AndroidWorldEnv.dockerfile` | `docker/android/Dockerfile` | Rename & Move |
| `examples/container_manager_demo.py` | `skyrl-agent/examples/run_android/` | Move |
| `docker_patches/` | - | Delete (use env vars) |
| `docker_env/.android/` | - | Delete (mount at runtime) |
| `verl/` | - | Delete (use integrations/verl/) |
| `docker/` (VeRL Dockerfiles) | - | Delete (already in SkyRL) |

---

## Key Design Principles

1. **Separation of Concerns**
   - `skyrl-agent`: WHAT (agents, tasks, tools) + WHERE (runtime environments)
   - `skyrl-train`: HOW (RL training backend - trainer, workers, PPO, etc.)
   - `docker/`: BUILD (container images)

2. **Configuration over Code Changes**
   - No file patching; use environment variables
   - YAML configs for settings
   - Runtime mount for SDK if needed

3. **Follow Existing Patterns**
   - Android agent in `agents/android/` like `agents/react/`
   - Android runtime in `runtime/android/` for environment access
   - Docker in `docker/android/` like `docker/Dockerfile`

4. **Single Source of Truth**
   - One `env.py` (configurable), not patches
   - One Docker folder structure
   - Configs in `configs/` directory

---

## Component Placement Summary

| Layer | Location | Contains |
|-------|----------|----------|
| **WHAT** (Agent logic) | `skyrl-agent/skyrl_agent/agents/android/` | Android agent implementation |
| **WHAT** (Task logic) | `skyrl-agent/skyrl_agent/tasks/android/` | Android task definitions |
| **WHERE** (Runtime) | `skyrl-agent/skyrl_agent/runtime/android/` | Container manager, runtime client |
| **HOW** (Training) | `skyrl-agent/skyrl_agent/integrations/verl/` | VeRL integration (already exists) |
| **HOW** (Training) | `skyrl-train/skyrl_train/` | Trainer, workers, generators |
| **BUILD** (Docker) | `docker/android/` | Dockerfile, FastAPI server |

---

## Quick Start Example

```python
import asyncio
from skyrl_agent.runtime.android import ContainerManager, RuntimeClient

async def main():
    # 1. Create container manager
    manager = ContainerManager(docker_image="androidworld:v8")
    
    # 2. Create pool of containers
    await manager.create_pool(
        pool_size=2,
        environment={
            "USE_SNAPSHOT": "false",
            "GPU_MODE": "swiftshader_indirect",
            "EMULATOR_BOOT_WAIT": "90",
        }
    )
    
    # 3. Allocate container for trajectory
    container = await manager.allocate_container()
    client = RuntimeClient(container)
    
    # 4. Run trajectory
    obs, info = await client.reset({"task_id": 0})
    while True:
        action = agent.act(obs)  # Your agent here
        obs, reward, done, _, info = await client.step(action)
        if done:
            break
    
    # 5. Cleanup
    await manager.release_container(container)
    await manager.cleanup()

asyncio.run(main())
```
