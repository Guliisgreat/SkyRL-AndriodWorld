# Integrating mini-swe-agent as a Third AndroidWorld Agent

**Status**: Proposed
**Date**: 2026-03-20
**Author**: Claude Code
**Branch**: `feat/cc-integrate-mini-swe-agent`

---

## 1. Why: Add a Third Agent with RL Training Support

We have two working agent implementations for AndroidWorld terminal tasks:

| Agent | Interface | LLM | Best SR | RL Training? |
|-------|-----------|-----|---------|-------------|
| **Claude Code CLI** | Claude CLI subprocess | Claude only | 83/87 (95%) oracle | No |
| **Terminus_2** | Harbor LiteLLM + Chat | Any (via LiteLLM) | 76/87 (87%) oracle | No |

Both work well, but **neither supports RL training**. mini-swe-agent adds a third option that:

- Is already integrated with SkyRL for RL training (`MiniSweAgentGenerator`)
- Uses LiteLLM — any model works (including locally-hosted models for training)
- Has a clean, minimal agent loop (156 lines) — easy to understand and modify
- Uses YAML-configured prompts — no code changes for prompt iteration
- Is proven on SWE-Bench — same observe→think→act→feedback pattern applies to AndroidWorld

**Goal**: Add mini-swe-agent as a third agent option with **minimal code changes** — just an environment adapter and a YAML config file. Keep Claude CLI and Terminus_2 as-is.

---

## 2. What: Minimal Additions

### 2.1 mini-swe-agent Core Loop (Already Exists)

```
DefaultAgent.run(task):
  1. Render system_template → system message
  2. Render instance_template → user message (with task)
  3. Loop:
     a. model.query(messages) → assistant response (THOUGHT + ```bash block```)
     b. Parse bash command from response
     c. env.execute(command) → {output, returncode}
     d. Render observation template → user message
     e. Check step_limit / cost_limit
  4. Return exit_status + submission
```

### 2.2 What We Need to Add

Only **two new things**:

1. **`AndroidWorldEnvironment`** (~80 lines) — implements `minisweagent.Environment` protocol, bridges to AndroidWorld containers via `android_env.py`
2. **`androidworld.yaml`** — YAML config with system prompt, templates, limits

Everything else is reused:
- `android_env.py` + all 6 tools (adb, sql, read-file, write-file, find-files, finish) — unchanged
- Container infrastructure (pool broker, skyrl_server, Docker) — unchanged
- Evaluation (force_eval, reset_container, reward) — unchanged
- mini-swe-agent library (DefaultAgent, Model, parsers) — unchanged

### 2.3 What Does NOT Change

- Claude Code CLI agent — stays as-is
- Terminus_2 agent — stays as-is
- `android_env.py` — stays as-is
- Container infrastructure — stays as-is
- Runner patterns (`run_parallel`, `run_sequential`, `finalize_results`) — reused from `claude_cli_common.py`

---

## 3. How: Implementation

### 3.1 New Files

```
skyrl-agent/examples/run_mini_swe/
├── androidworld.yaml          # Agent config (templates, limits)
├── run_agent.py               # Mode 1: single attempt (reuses claude_cli_common helpers)
├── run_oracle.py              # Mode 2: oracle retries
└── mini_swe_common.py         # Bridge: mini-swe-agent ↔ AndroidWorld containers

skyrl-agent/skyrl_agent/agents/android/mini_swe/
├── __init__.py
└── environment.py             # AndroidWorldEnvironment (~80 lines)
```

### 3.2 `AndroidWorldEnvironment` — The Only New Code

Implements mini-swe-agent's `Environment` protocol by running commands through `android_env.py`:

```python
class AndroidWorldEnvironment:
    """Adapts AndroidWorld containers to mini-swe-agent's Environment protocol."""

    def __init__(self, container_url, state_file, android_env_script, timeout=120):
        self.config = EnvironmentConfig(...)
        self._env = {
            **os.environ,
            "ANDROID_SERVER_URL": container_url,
            "ANDROID_STATE_FILE": state_file,
            "ANDROID_DISABLE_TREE": "1",
        }

    def execute(self, action: dict, cwd: str = "") -> dict:
        """Run a bash command on the host (which calls android_env.py)."""
        result = subprocess.run(action["command"], shell=True,
                                capture_output=True, text=True,
                                env=self._env, timeout=self.config.timeout)
        return {"output": result.stdout + result.stderr, "returncode": result.returncode}

    def get_template_vars(self) -> dict:
        return {"android_env_script": self.config.android_env_script}

    def serialize(self) -> dict:
        return {"info": {"environment": "androidworld"}}
```

### 3.3 `androidworld.yaml` — Config

Adapts the v2 clean prompt to mini-swe-agent's Jinja2 template format:

```yaml
agent:
  system_template: |
    You are an Android automation agent. You control an Android device through
    CLI tools. Each command runs to completion via subprocess.

    Do NOT use any GUI interaction — no screenshots, no accessibility trees,
    no tap/swipe/keyevent input, no screen coordinates.

    Your response must contain exactly ONE bash code block.
    Include a THOUGHT section before your command.

    ## Tools
    python {{ android_env_script }} adb "adb shell <cmd>"
    python {{ android_env_script }} sql <db_path> "<SQL>"
    python {{ android_env_script }} read-file <device_path>
    python {{ android_env_script }} write-file <device_path> "<content>"
    python {{ android_env_script }} find-files <directory> "<pattern>"
    python {{ android_env_script }} finish --status complete --description "<answer>"

    ## Strategy
    1. Discover — find package, databases, files
    2. Inspect — read schemas and existing data
    3. Act — use sql/write-file for changes
    4. Verify — confirm changes persisted
    5. Sync — force-stop app, call finish

  instance_template: |
    ## Task
    {{ task }}

  action_observation_template: |
    <returncode>{{ output.returncode }}</returncode>
    <output>
    {{ output.output[:12000] }}
    </output>

  step_limit: 30
  cost_limit: 5.0

model:
  model_name: ""
  model_kwargs:
    drop_params: true
```

### 3.4 Runner Scripts

Thin wrappers that:
1. Load tasks from JSONL
2. For each task: create `AndroidWorldEnvironment`, create `DefaultAgent`, call `agent.run(task_text)`
3. Extract reward via `force_eval(container_url)`
4. Reuse `run_parallel` / `finalize_results` from `claude_cli_common.py`

---

## 4. Response Format Comparison

### Claude Code CLI (free-form):
```
I'll search for the app's database.

python android_env.py adb "adb shell pm list packages | grep calendar"
python android_env.py find-files /data/data/com.simplemobiletools.calendar.pro/databases "*.db"
```

### Terminus_2 (structured JSON):
```json
{
  "analysis": "Need to find the calendar app database",
  "plan": "Search for package and locate databases",
  "commands": [
    "python android_env.py adb \"adb shell pm list packages | grep calendar\"",
    "python android_env.py find-files /data/data/com.simplemobiletools.calendar.pro/databases \"*.db\""
  ],
  "task_complete": false
}
```

### mini-swe-agent (THOUGHT + bash block):
```
THOUGHT: I need to find the calendar app's database. I'll search for the package first.

```bash
python android_env.py adb "adb shell pm list packages | grep calendar" && python android_env.py find-files /data/data/com.simplemobiletools.calendar.pro/databases "*.db"
```
```

Key difference: mini-swe-agent enforces **one bash block per step** with `&&` chaining for multiple commands. This is cleaner for RL training (clear action boundaries).

---

## 5. RL Training Path

Once the adapter works for inference evaluation, RL training requires:

1. Create `AndroidWorldGenerator` extending `MiniSweAgentGenerator`
2. Override environment setup: `AndroidWorldEnvironment` instead of Docker/SWE-Bench
3. Override evaluation: `force_eval(container_url)` returns reward 0 or 1
4. Same GRPO/PPO training loop — just different environment + reward signal

This is Phase 2 — not in this PR.

---

## 6. Expected Results

Based on mini-swe-agent's design (single bash command, THOUGHT reasoning, LiteLLM):

| Metric | Expected | Rationale |
|--------|----------|-----------|
| Agent SR (Sonnet 4.6) | 70-80/87 (80-92%) | Between Terminus_2 (82%) and Claude CLI (86%) |
| Oracle SR (Sonnet 4.6) | 75-83/87 (86-95%) | Single-command-per-step may need more retries |
| Agent SR (gpt-5.3-codex) | 50-60/87 (57-69%) | Similar to Terminus_2 (63%) |

The main question is whether one-command-per-step hurts (more steps needed) or helps (cleaner actions, fewer errors).

---

## 7. Implementation Checklist

- [ ] `AndroidWorldEnvironment` in `skyrl_agent/agents/android/mini_swe/environment.py`
- [ ] `androidworld.yaml` in `examples/run_mini_swe/`
- [ ] `mini_swe_common.py` — bridge helpers (load config, setup env, run task)
- [ ] `run_agent.py` — Mode 1 runner
- [ ] `run_oracle.py` — Mode 2 runner
- [ ] Test on 16-task diagnostic subset
- [ ] Test on full 87-task eval
- [ ] Compare with Terminus_2 and Claude CLI results
