# MobileWorld × Harbor: Usage Guide

## Overview

Run MobileWorld benchmark tasks through Harbor's evaluation framework using Claude Code CLI as the agent. Harbor manages the full lifecycle: spin up Docker container with Android emulator → initialize task → run Claude Code agent → evaluate → teardown.

**Baseline results (2026-04-03):** 26/137 tasks passed (19.0% SR) with Claude Sonnet 4.6, 30 max turns, no GUI.

## Prerequisites

- Docker with KVM support (`/dev/kvm`)
- Harbor CLI installed (`pip install harbor-ai`)
- Claude Code CLI installed in the Docker image
- OAuth token or API key for Claude

## Quick Start

```bash
cd /path/to/SkyRL-AndriodWorld/harbor

# 1. Build the Docker image (one-time, ~20s if base image cached)
cd adapters/mobileworld/template/environment
docker build -t ghcr.io/tongyi-mai/mobile_world:harbor .
cd /path/to/SkyRL-AndriodWorld/harbor

# 2. Run a single task
harbor run \
  -p ./datasets/mobileworld \
  --agent claude-code \
  --model anthropic/claude-sonnet-4-6 \
  --n-concurrent 1 \
  --n-tasks 1 \
  --ae "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN" \
  --ae MW_DISABLE_TREE=1 \
  --ak max_turns=30 \
  --timeout-multiplier 3.0 \
  --no-delete

# 3. Run all non-backend tasks (4 concurrent, ~3 hours)
harbor run \
  -p ./datasets/mobileworld \
  --agent claude-code \
  --model anthropic/claude-sonnet-4-6 \
  --n-concurrent 4 \
  --ae "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN" \
  --ae MW_DISABLE_TREE=1 \
  --ak max_turns=30 \
  --timeout-multiplier 3.0 \
  --no-delete \
  -x "mw-mastodon-*" \
  -x "mw-mattermost-*" \
  -x "mw-local-file-*" \
  -x "mw-adjust-*" \
  -x "mw-change-wallpaper-*" \
  -x "mw-close-flight-*" \
  -x "mw-open-flight-*"
```

## Key Flags

| Flag | Purpose |
|------|---------|
| `-p ./datasets/mobileworld` | Path to the generated Harbor dataset |
| `--n-concurrent 4` | Run 4 tasks in parallel. Max ~4-5 per machine (KVM contention). |
| `--no-delete` | Keep Docker image after run. Without this, `--rmi all` deletes the 20GB image. |
| `--timeout-multiplier 3.0` | Emulator boot takes ~3.5 min; multiply default timeouts. |
| `--ae KEY=VALUE` | Pass env vars to the agent (auth token, MW config). |
| `--ak max_turns=30` | Claude Code max conversation turns. |
| `-t "mw-task-name"` | Run specific task(s). Repeatable. |
| `-x "mw-pattern-*"` | Exclude tasks by glob pattern. Repeatable. |

## Task Selection

### By backend requirement

| Category | Tasks | Needs | Notes |
|----------|-------|-------|-------|
| Non-backend | 139 | Nothing | Settings, native, gmail, calendar, mall, map, chrome |
| Mastodon | 41 | Mastodon docker-in-docker | 8 CPU, 16GB RAM, 45s backend wait |
| Mattermost | 18 | Mattermost docker-in-docker | 8 CPU, 16GB RAM, 45s backend wait |

### By difficulty (baseline SR)

| Category | Tasks | SR | Best for |
|----------|-------|----|----------|
| native | 29 | 45% | File ops, PDF reading, SMS, photos |
| calendar | 7 | 29% | DB queries, compound tasks |
| mall | 8 | 25% | Cart/order queries |
| gmail | 16 | 0% | Email reply — needs subject fix |
| map | 5 | 0% | Needs Google Maps interaction |

### Run specific task

```bash
harbor run -p ./datasets/mobileworld --agent claude-code \
  --model anthropic/claude-sonnet-4-6 \
  -t "mw-check-conference-duration-task" \
  --ae "CLAUDE_CODE_OAUTH_TOKEN=$TOKEN" --ak max_turns=30 \
  --timeout-multiplier 3.0 --no-delete
```

### Run a category

```bash
# Run only calendar tasks
harbor run -p ./datasets/mobileworld --agent claude-code \
  --model anthropic/claude-sonnet-4-6 \
  -t "mw-check-conference-*" -t "mw-check-deduplicated-*" \
  -t "mw-schedule-*" \
  --ae "CLAUDE_CODE_OAUTH_TOKEN=$TOKEN" --ak max_turns=30 \
  --timeout-multiplier 3.0 --no-delete --n-concurrent 4
```

## Results

Results are written to `harbor/jobs/<timestamp>/`.

```bash
# Summary
cat jobs/<timestamp>/result.json | python3 -m json.tool

# Per-task results
for d in jobs/<timestamp>/mw-*/; do
  task=$(basename "$d" | sed 's/__.*//');
  score=$(python3 -c "import json; print(json.load(open('${d}verifier/reward.json'))['score'])" 2>/dev/null);
  reason=$(python3 -c "import json; print(json.load(open('${d}verifier/reward.json'))['reason'][:80])" 2>/dev/null);
  echo "$task | $score | $reason";
done

# Agent trace for a specific task
cat jobs/<timestamp>/mw-some-task__*/agent/claude-code.txt

# Agent step-by-step actions
python3 -c "import json; d=json.load(open('jobs/<timestamp>/mw-some-task__*/agent/state.json'));
[print(f'step {r[\"step_idx\"]}: {r[\"action_type\"]}') for r in d['step_records']]"
```

## Regenerating the Dataset

If you modify the prompt template or adapter logic:

```bash
cd /path/to/SkyRL-AndriodWorld/harbor

python adapters/mobileworld/run_adapter.py \
  --mw-repo ../MobileWorld \
  --output-dir ./datasets/mobileworld \
  --filter all \
  --gt-commands ../skyrl-agent/examples/run_mobileworld/gt_commands_mwenv.json
```

This regenerates all 201 task directories in `datasets/mobileworld/`. Key files per task:

```
datasets/mobileworld/mw-<task-name>/
├── task.toml                    # Config: image, resources, timeouts, env vars
├── instruction.md               # Prompt sent to Claude Code CLI
├── environment/
│   ├── docker-compose.yaml      # Container config (task name hardcoded)
│   ├── Dockerfile               # Extends base MW image (not used at runtime)
│   ├── harbor_entrypoint.sh     # Boot: emulator → server → task init → ready
│   ├── mw_env.py                # CLI wrapper for phone control
│   └── server_exec_patch.py     # Adds /exec endpoint to MW server
├── tests/
│   ├── test.sh                  # Verifier: calls /task/eval, writes reward
│   └── eval_config.json         # Task name, device ID, backend flags
└── solution/
    └── solve.sh                 # Oracle ground truth (88 tasks have this)
```

## Architecture

```
Harbor CLI
  └─ docker compose up (per task)
       └─ ghcr.io/tongyi-mai/mobile_world:harbor
            ├─ harbor_entrypoint.sh
            │   ├─ Boot Android emulator (~3 min)
            │   ├─ Start MobileWorld server (port 6800)
            │   ├─ Restart server (fix emulator detection race)
            │   ├─ POST /task/init (initialize task)
            │   └─ touch /tmp/mw_ready (health signal)
            │
            ├─ Claude Code CLI (agent phase)
            │   └─ Bash tool → python mw_env.py <cmd>
            │       ├─ adb "adb shell ..."  → /exec endpoint
            │       ├─ sql <db> "<SQL>"      → /exec endpoint
            │       ├─ read-file / write-file
            │       ├─ http / exec           → backend APIs
            │       └─ finish                → /step + state.json
            │
            └─ test.sh (verifier phase)
                ├─ GET /task/eval → {"score": 0.0/1.0, "reason": "..."}
                ├─ Write /logs/verifier/reward.txt
                └─ POST /task/tear_down
```

## Known Issues

1. **`--no-delete` required** — Without it, Harbor runs `docker compose down --rmi all` which removes the 20GB image. Rebuild with `docker build -t ghcr.io/tongyi-mai/mobile_world:harbor .` if lost.

2. **Max ~4-5 concurrent** — Each container needs KVM for the Android emulator. At 7+ concurrent, emulator boot times out due to KVM contention. 4 is safe.

3. **Emulator boot ~3.5 min** — The `--timeout-multiplier 3.0` is required to avoid health check timeouts. Each task takes ~5 min total (3.5 min boot + 1-2 min agent + 10s verifier).

4. **`MW_TASK_NAME` must be hardcoded** — Harbor passes `[environment.env]` vars to `docker compose exec` but NOT to `docker compose up`. The entrypoint needs the task name at startup, so it's baked into `docker-compose.yaml` by the adapter. If you add tasks manually, set this in the compose file.

5. **Agent compound tasks** — The agent (Claude Sonnet 4.6) scores 45% on single-step tasks but 0% on gmail tasks requiring email replies with exact `Re:` subject format. Multi-step tasks (read → send SMS/set alarm) are the main failure mode.

## Files Changed from Base Harbor

| File | Change |
|------|--------|
| `adapters/mobileworld/adapter.py` | Substitutes placeholders in both `task.toml` and `docker-compose.yaml` |
| `adapters/mobileworld/template/environment/docker-compose.yaml` | `MW_TASK_NAME` and `MW_BACKEND_WAIT` hardcoded via `{{ }}` placeholders instead of `${VAR:-}` interpolation |
| `adapters/mobileworld/template/instruction.md` | Rich prompt with tools, data locations, compound task guidance, self-verification rules |
