# Claude Agent SDK Baseline for AndroidWorld

## Overview

This integration adds the Claude Agent SDK (`pip install claude-agent-sdk`) as a
new evaluation baseline for AndroidWorld.  The SDK provides an autonomous agent
loop — Claude Code as a library — with built-in tool use and MCP support.
Instead of fitting into the existing `AsyncInferBackend` -> `AndroidAgent.step()`
pipeline, the SDK's `query()` function **replaces the entire agent loop**.
Custom MCP tools bridge to the existing container infrastructure (`RuntimeClient`).

**Action space**: ADB commands only (no GUI coordinates).
**Observation**: Accessibility tree (uiautomator dump XML) — pure text, no
screenshots.
**Constraint**: No modifications to existing files. Only new files that import
and reuse existing classes.

```
run_claude_sdk_android.py   (entry point)
  -> ClaudeSDKRunner.run(data)
       -> AndroidTask.initialize_runtime()   [container pool]
       -> async_fix_pool_android dispatcher:
            per instance:
              init_fn   -> ClaudeSDKTrajectory.initialize_trajectory()
              run_fn    -> ClaudeSDKTrajectory.generate_trajectory()
              eval_fn   -> ClaudeSDKTrajectory.evaluate_trajectory()
       -> collect results -> metrics
```

---

## Architecture

### Why not reuse AgentRunner + AndroidAgent?

The existing pipeline is built around a tight loop:

```
AgentRunner  ->  AndroidTrajectory  ->  AndroidAgent.step()  ->  AsyncInferBackend
                                            ^                         |
                                            |  messages/images        v
                                            +-- env.step_adb() <-- vLLM / OpenAI
```

Each `step()` call does: select messages -> tokenize -> infer -> parse action ->
execute -> append observation -> repeat.  The runner owns the inference engine;
the trajectory owns the agent; the agent owns the conversation.

The Claude Agent SDK cannot fit into this pattern because:

1. **The SDK owns the loop.** `query()` is a black-box async iterator that
   internally decides when to call tools, how to format messages, and when to
   stop.  There is no per-step hook to inject our `step()` logic.

2. **No tokenizer / inference engine needed.** The SDK manages its own API
   calls, context window, retries, and rate limiting.  Passing `None` for
   `infer_engine` and `tokenizer` to `AgentRunner.__init__` triggers code paths
   that assume a real backend (VLM processor loading, backend construction).

3. **No training data.** The SDK produces no token IDs, loss masks, or VLM
   tensors.  The runner's `_post_process_results()` can be radically simpler.

The cleanest solution is a **standalone runner** (`ClaudeSDKRunner`) that reuses
the infrastructure components (`AndroidTask`, `ContainerManager`,
`DISPATCHER_REGISTRY`, `TrajectorySaver`) directly, without inheriting from
`AgentRunner`.

### Component Diagram

```
+-------------------+       +------------------------+       +------------------+
| run_claude_sdk_   |       |   ClaudeSDKRunner      |       |   AndroidTask    |
| android.py        | ----> |                        | ----> | (unchanged)      |
| (entry point)     |       | - _initialize_trajs()  |       | - initialize_    |
|                   |       | - run()                |       |   runtime()      |
+-------------------+       | - _post_process()      |       | - evaluate_      |
                             +----------+-------------+       |   result()       |
                                        |                     +------------------+
                     dispatches via      |
                     async_fix_pool_android
                                        |
                            +-----------v-----------+
                            | ClaudeSDKTrajectory   |
                            | (extends BaseTrajectory)|
                            |                       |
                            | initialize_trajectory |-----> RuntimeClient.reset()
                            | generate_trajectory   |-----> claude_agent_sdk.query()
                            | evaluate_trajectory   |-----> AndroidTask.evaluate_result()
                            +-----------+-----------+
                                        |
                                calls make_android_tools()
                                        |
                            +-----------v-----------+
                            | MCP Tools (in-process)|
                            |                       |
                            | run_adb_command ------+-----> RuntimeClient.step_adb()
                            | get_accessibility_   |
                            |   tree ------+-------+-----> RuntimeClient.step_adb()
                            | finish_task ---------+-----> RuntimeClient.step()
                            +-----------------------+
```

---

## File-by-File Design

### 1. `claude_sdk_tools.py` — MCP Tool Factory

**Pattern**: closure-based factory.  `make_android_tools(runtime_client)` returns
`(tools_list, shared_state)`.

```python
tools, state = make_android_tools(runtime_client)
#  tools:  [run_adb_command, get_accessibility_tree, finish_task]
#  state:  {"step_count": 0, "terminated": False, ...}
```

Each tool is defined with the SDK's `@tool(name, description, schema)` decorator
inside the factory function body, so it closes over both `runtime_client` and
`state`.  This means:

- Tools call `runtime_client.step_adb()` / `runtime_client.step()` **directly**,
  in-process, with zero serialization overhead.
- The shared `state` dict is mutated by each tool call and read by the
  trajectory after `query()` completes.  No files, no IPC.

**Tools**:

| Tool                     | Calls                        | Returns                          |
|--------------------------|------------------------------|----------------------------------|
| `run_adb_command`        | `RuntimeClient.step_adb()`   | text (command output)            |
| `get_accessibility_tree` | `RuntimeClient.step_adb()` (`uiautomator dump`) | text (UI hierarchy XML) |
| `finish_task`            | `RuntimeClient.step()`       | text (confirmation)              |

**Pure text agent**: all tool responses are text-only.  The agent observes the
screen by calling `get_accessibility_tree`, which runs
`adb shell uiautomator dump /dev/tty` and returns the XML.  No screenshots, no
images, no base64 encoding.

**Safety**: reuses the same `ALLOWED_PREFIXES` and `BLOCKED_PATTERNS` from
`android_api_screen_adb_agent.py`.  Commands not on the allowlist are rejected
before reaching the container.

**Shared state dict**:
```python
{
    "step_count": int,           # incremented by run_adb_command
    "terminated": bool,          # set by finish_task or environment signal
    "reward": float,             # last reward from environment
    "finish_status": str,        # "complete" | "infeasible"
    "finish_description": str,   # agent's description of outcome
    "step_records": List[dict],  # per-step metadata for TrajectorySaver
}
```

### 2. `claude_sdk_trajectory.py` — Trajectory Lifecycle

Extends `BaseTrajectory` to keep the same init/generate/evaluate lifecycle that
the `async_fix_pool_android` dispatcher expects.

**Key difference from `AndroidTrajectory`**: does NOT create an `AndroidAgent`.
The SDK IS the agent.

**Sentinel class** (`ClaudeAgentSDK`): an empty class that exists solely so
`_import_object(cfg.agent_cls)` succeeds during `BaseTrajectory.__init__`.  It
is never instantiated.  The YAML config references it as:
```yaml
agent_cls: skyrl_agent.agents.android.claude_sdk_trajectory.ClaudeAgentSDK
```

**System prompt** (`CLAUDE_ADB_SYSTEM_PROMPT`): a comprehensive ADB command
reference adapted from `ADB_AGENT_PROMPT` in `android_api_screen_adb_agent.py`.
The key adaptation is removing the `Thought:/Command:` output format — the SDK
uses tool calls natively, so no text parsing is needed.

**`generate_trajectory()` flow**:

```
1. make_android_tools(self.env_handle)     -> tools, tools_state
2. create_sdk_mcp_server("android", tools) -> android_server
3. ClaudeAgentOptions(
       model=..., system_prompt=..., max_turns=30,
       permission_mode="bypassPermissions",
       mcp_servers={"android": android_server}
   )
4. async for message in query(prompt=task_text, options=options):
       collect messages
5. Read tools_state -> build self.result
```

Step 4 is where the SDK takes over.  It autonomously calls `run_adb_command`
and `get_accessibility_tree`, reads the UI hierarchy XML, decides what to do
next, and eventually calls `finish_task` (or hits `max_turns`).

**`evaluate_trajectory()`**: identical to `AndroidTrajectory` — calls
`AndroidTask.evaluate_result()` which uses the environment's ground-truth
reward.

**Result format**: matches the existing trajectory result schema:
```python
{
    "instance_id", "trajectory_id", "messages", "history_images",
    "train_dict": {},   # empty — no training data
    "results", "finish_reason", "reward", "step_count",
    "step_records",     # from tools_state, for TrajectorySaver
    ...
}
```

### 3. `claude_sdk_runner.py` — Standalone Runner

Does NOT inherit from `AgentRunner`.  `AgentRunner.__init__` requires
`infer_engine` and triggers VLM processor loading, backend construction, and
tokenizer setup — none of which apply here.

Instead, `ClaudeSDKRunner` directly uses:

| Component           | How it's used                                         |
|---------------------|-------------------------------------------------------|
| `AndroidTask`       | `initialize_runtime()` for container pool, `evaluate_result()` for reward |
| `ContainerManager`  | via `AndroidTask._container_manager`, for allocate/release |
| `RuntimeClient`     | created in `init_fn` from the allocated container       |
| `DISPATCHER_REGISTRY` | `async_fix_pool_android` for parallel dispatch        |
| `TrajectorySaver`   | per-trajectory persistence (JSON + PNGs)               |
| `TrajectoryConfig`  | lightweight config dataclass for each trajectory        |

**Dispatch callbacks**:
```python
init_fn(batch_idx, traj_id, container):
    traj.env_handle = RuntimeClient(container)
    traj.initialize_trajectory()         # -> env reset

run_fn(batch_idx, traj_id, container):
    traj.generate_trajectory()           # -> SDK query()

eval_fn(batch_idx, traj_id, container):
    traj.evaluate_trajectory()           # -> ground-truth reward
```

**Post-processing** (`_post_process_results()`): collects rewards, step counts,
and finish reasons.  Computes rollout metrics (raw_reward, avg_step_count,
finish/infeasible/error ratios).  No training tensors.

### 4. `run_claude_sdk_android.py` — Entry Point

Modeled after `run_openai_android_inference.py`.  Handles:

- CLI parsing: `--data`, `--model`, `--pool-size`, `--max-instances`,
  `--max-turns`, `--output-dir`
- JSONL loading (same format as OpenAI script)
- YAML config loading + CLI overrides
- Runner creation and execution
- Metrics computation and saving (`final_metrics.json`, `rewards.json`)

No tokenizer needed.  No wandb integration (can be added later).

### 5. `claude_sdk_android.yaml` — Configuration

Minimal config:
```yaml
agent_cls: skyrl_agent.agents.android.claude_sdk_trajectory.ClaudeAgentSDK
task: skyrl_agent.tasks.android.android_task.AndroidTask

env:
  pool_size: 16
  buffer_size: 2
  docker_image: androidworld:full_adb_agent
  ...

claude_sdk:
  model: claude-sonnet-4-20250514
  max_turns: 30
  permission_mode: bypassPermissions
```

No `generator` section (no inference backend).  No `dispatcher` section (runner
configures the dispatcher directly).

### 6. `run_claude_sdk.sh` — Shell Launcher

Sets environment variable defaults, validates `ANTHROPIC_API_KEY`, and calls the
Python entry point.  Supports `MAX_INSTANCES` for quick debugging:
```bash
ANTHROPIC_API_KEY=sk-ant-... MAX_INSTANCES=2 ./run_claude_sdk.sh
```

---

## Design Decisions

### In-process MCP tools vs subprocess

The Claude Agent SDK supports two MCP server modes:

1. **Subprocess** (stdio): SDK launches a separate process, communicates via
   JSON-RPC over stdin/stdout.  Tools run in isolation.
2. **In-process**: SDK calls tool functions directly in the same process via
   `create_sdk_mcp_server()`.

We use in-process because:

- **RuntimeClient is async and in-process.**  The tools need to `await
  runtime_client.step_adb()`.  Doing this across a process boundary would
  require serializing the RuntimeClient connection (HTTP URL + port) and
  creating a new aiohttp session in the subprocess.  In-process closures are
  simpler and faster.

- **Shared state is trivial.**  The `state` dict is a plain Python dict
  mutated by tool closures and read by the trajectory.  No files, no
  serialization, no race conditions.

### Sentinel class instead of registry entries

The existing codebase uses two registries (`AGENT_GENERATOR_REGISTRY`,
`AGENT_TRAJECTORY_REGISTRY`) to map agent class paths to runner and trajectory
class paths.  These are used by `AutoAgentRunner.from_task()`.

We do NOT add entries to these registries because:

1. The plan requires no modifications to existing files.
2. `ClaudeSDKRunner` is standalone — it doesn't use `AutoAgentRunner`.
3. The sentinel `ClaudeAgentSDK` only needs to be importable (for
   `_import_object()` in `BaseTrajectory.__init__`), not registered.

### No training data

`train_dict` is always `{}`.  The SDK produces no token IDs, logprobs, or
gradient-relevant data.  This baseline is evaluation-only.

### Cost and rate limits

At 16 parallel containers, the SDK makes 16 concurrent `query()` calls.  Each
call can generate 30+ API round-trips (one per tool call).  Considerations:

- **Cost**: ~$5-15 for a full 234-instance run with claude-sonnet.
- **Rate limits**: The SDK has built-in retry/backoff for Anthropic rate limits.
  If insufficient, reduce `pool_size` in the YAML config or via `--pool-size`.
- **Quick testing**: Use `--max-instances 2 --pool-size 2` for a fast sanity
  check (~$0.10).

---

## Quick Start

```bash
# Install
pip install claude-agent-sdk

# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Ensure Docker containers are running
# (androidworld:full_adb_agent image)

# Quick test (2 instances)
cd skyrl-agent/examples/run_claude_sdk
python run_claude_sdk_android.py \
    --data ../../data/androidworld_generalization/unseen_task_instance/test.jsonl \
    --max-instances 2 --pool-size 2

# Full run
./run_claude_sdk.sh

# Check results
cat results/final_metrics.json
cat results/rewards.json
```

---

## File Inventory

```
skyrl-agent/
  skyrl_agent/agents/android/
    claude_sdk_tools.py         273 lines   MCP tool factory
    claude_sdk_trajectory.py    270 lines   Trajectory lifecycle
    claude_sdk_runner.py        257 lines   Standalone runner

  examples/run_claude_sdk/
    run_claude_sdk_android.py   216 lines   Entry point
    claude_sdk_android.yaml      31 lines   Configuration
    run_claude_sdk.sh           100 lines   Shell launcher
    DESIGN.md                              This document
```

Total: ~1150 lines of new code. Zero modifications to existing files.
