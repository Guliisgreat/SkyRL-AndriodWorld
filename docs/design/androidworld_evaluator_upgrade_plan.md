# Upgrade AndroidWorld Evaluator from 2024 Fork to Latest (2026)

**Date:** 2026-03-10
**Branch:** TBD (`feat/cc-upgrade-androidworld-evaluator`)
**Status:** Proposed
**Author:** Li (generated with Claude Code)
**Related:** [Confluence: AndroidWorld Evaluator Changes 2024 vs 2026](https://li-gu.atlassian.net/wiki/spaces/awg/pages/211910657)

## 1. Motivation

Our local AndroidWorld evaluator is a 2024 fork of `google-research/android_world` with several custom patches. The upstream repo has since accumulated **35+ commits** affecting evaluation logic, reliability, and fairness. Key issues with our current fork:

| Issue | Impact |
|-------|--------|
| SMS field name `"message"` vs upstream `"body"` | Silent evaluation failures on SMS tasks |
| Missing `\r` stripping in ADB output parsing | False negatives on string comparisons |
| Missing `app_names` for SMS, Markor, expense, system tasks | Apps not snapshot-restored between runs |
| `clear_app_data` commented out for Chrome | State leakage across browser tasks |
| Lower complexity scores (fewer max steps) | Agents get fewer steps than upstream allows |
| No race condition fixes for parallel emulators | Flaky failures in `file_utils.py` |
| Clock stopwatch cleanup uses hardcoded tap coords | Fragile, device-dependent |

Upgrading ensures fair benchmarking, reduces flaky failures, and aligns with the community standard.

## 2. Architecture

### Current State

```
aw_g_original/docker_env/RL4AndroidWorld/
├── android_world/           ← 2024 fork + custom patches (OUTDATED)
├── android_env/             ← DeepMind android-env (may be outdated)
├── server/                  ← Our custom FastAPI server (KEEP)
├── entrypoint.sh            ← Container startup (KEEP)
└── requirements.txt         ← Server deps: fastapi, uvicorn, gymnasium

docker/android/
├── Dockerfile               ← Base image build (androidworld:v8)
├── Dockerfile.full_adb_agent← Layer: ADB port + /step_adb + ui_elements
├── server/                  ← Our patched server (env.py, server.py)
└── entrypoint.sh            ← Our patched entrypoint
```

### Key Architectural Insight

**android_world is fully encapsulated in Docker containers.** The host-side `skyrl-agent/` never imports android_world — it communicates exclusively via HTTP (`/reset`, `/step`, `/step_adb`, `/health`). This means:

- Updating android_world = replace code in Docker build context + rebuild image
- No changes needed in `skyrl-agent/`, `container_manager.py`, or agent code
- Our custom server patches (`/step_adb`, ADB port support) live in `docker/android/server/` and are applied as a layer on top — they don't touch android_world internals

### Target State

```
aw_g_original/docker_env/RL4AndroidWorld/
├── android_world/           ← UPDATED to latest upstream (2026)
├── android_world_2024/      ← Backup of current fork (for reference)
├── android_env/             ← Updated if upstream changed it
├── server/                  ← UNCHANGED (our custom code)
├── entrypoint.sh            ← UNCHANGED
└── requirements.txt         ← Updated if new deps needed

docker/android/
├── Dockerfile               ← FROM tag updated, rebuild as androidworld:v10
├── Dockerfile.full_adb_agent← FROM updated to androidworld:v10
├── server/                  ← UNCHANGED (our patches)
└── entrypoint.sh            ← UNCHANGED
```

## 3. What Changes (Upstream 2024 → 2026)

### 3.1 Bug Fixes (15 commits)

| Commit | File | Fix |
|--------|------|-----|
| `bc9c83d9` | osmand.py | Name-based location parsing in favorites |
| `2be65ec8` | osmand.py | Favorites file cleanup (checked host path instead of device) |
| `caace4e0` | audio_recorder.py | Clear entire directory, not single file |
| `00104f11` | audio_recorder.py | Set-based recording detection (was count-based) |
| `34012d69` | clock.py | Clear app data in init/teardown (replaces hardcoded taps) |
| `dfc17ef5` | markor.py | MarkorMergeNotes initialization order |
| `f68f6d38` | simple_gallery_pro.py | Avoid mutating params dict |
| `623cc0f0` | sqlite_validators.py, calendar_utils.py | DB clearing at init start (not just teardown) |
| `247d3091` | sms_validators.py, sms.py | SMS timing fix + field name `"message"` → `"body"` |
| `60dfa07b` | retro_music.py | Float → int conversion for duration |
| `f6a1d2c5` | retro_music.py | Cast `is_successful` return to float |
| `4eb73fca` | contacts.py | Fallback phone label element finder |
| `ad17237f` | contacts.py | Include invisible elements in contact draft check |
| `e46b796f` | browser.py | Hide number after entry to reduce ambiguity |
| `33897828` | information_retrieval_registry.py | Prevent TASK_REGISTRY override |

### 3.2 Strictness/Leniency Changes

| Commit | File | Change | Direction |
|--------|------|--------|-----------|
| `1854a2bf` | clock.py | `n_stopwatch == 2` → `>= 2` | More lenient |
| `7711a1c8` | sms_validators.py | Detect stuck "Sending" state | More strict |
| `5124d37d` | information_retrieval.py | Only clear relevant DB | More lenient |
| `4b8f95eb` | task_eval.py | Skip JSON schema validation | More lenient |
| `29b5a757` | markor/sms/system/task_eval.py | Add `app_names`, skip clipper snapshot | Reliability |

### 3.3 Complexity / Max Steps (~2× increase)

| Task | 2024 (ours) | 2026 (upstream) |
|------|-------------|-----------------|
| Calendar: Add events | 2.0 | 3.4 |
| Expense: Add from Markor | 3.0 | 6.0 |
| Expense: Add from Gallery | 2.0 | 6.0 |
| Recipe: from Markor | 4.8 | 6.0 |
| Recipe: from image | 2.6 | 6.0 |
| FilesDeleteFile | 1.0 | 2.2 |
| SMS | 1.0 | 1.2 |

### 3.4 Reliability / Infrastructure (10 commits)

- `file_utils.py`: `os.path.join` → `convert_to_posix_path()`, `\r` stripping, `tempfile.mkdtemp()` for parallel safety, path escaping fixes
- `task_eval.py`: `setup_datetime()` before every task, `random.seed(seed)`, try/except on `close_recents`
- `browser.py`: Use real time instead of fixed Oct 15, 2023
- `osmand.py`: App launch wait 2s → 7s

### 3.5 IR Calendar Ground Truth Fix

- `ef89d938`: Combined `start_date` + `start_time` exclusion conditions into single datetime comparison. Prevents noise events from overlapping with task targets. (~200 lines, 16 new tests.)

## 4. Implementation Plan

### Phase 1: Pull Latest Source (~15 min)

```bash
# Clone upstream to temp location
git clone https://github.com/google-research/android_world /tmp/android_world_upstream

# Record upstream commit hash for reproducibility
cd /tmp/android_world_upstream && git rev-parse HEAD > /tmp/upstream_commit.txt
```

### Phase 2: Identify Our Custom Patches (~30 min)

Before replacing, catalog every local modification so nothing is lost:

| File | Our Custom Change | Action |
|------|-------------------|--------|
| `android_world/registry.py` | EASY/MEDIUM/HARD difficulty tiers | Re-apply on top of upstream registry |
| `android_world/registry_original.py` | Backup of original registry | Delete (no longer needed) |
| `server/server.py` | NOT in android_world package | Keep as-is (our code) |
| `server/env.py` | NOT in android_world package | Keep as-is (our code) |

**Critical**: Our server code (`RL4AndroidWorld/server/`) is separate from the android_world package. It imports from android_world but is NOT part of it. No risk of overwrite.

### Phase 3: Replace android_world Package (~15 min)

```bash
cd aw_g_original/docker_env/RL4AndroidWorld/

# Backup current
mv android_world android_world_2024

# Copy upstream (just the android_world package, not the entire repo)
cp -r /tmp/android_world_upstream/android_world .

# Verify setup.py exists
ls android_world/setup.py

# Check for new dependencies
diff android_world_2024/requirements.txt android_world/requirements.txt
```

### Phase 4: Re-apply Custom Registry (if needed) (~15 min)

If we still need EASY/MEDIUM/HARD task splits:

```python
# In android_world/android_world/registry.py, append after ANDROID_TASK_REGISTRY:
EASY = [...]
MEDIUM = [...]
HARD = [...]
```

Alternatively, move this to our own code outside android_world (cleaner separation).

### Phase 5: Check android_env Compatibility (~15 min)

```bash
# Compare android_env versions
diff -rq android_env/ /tmp/android_world_upstream/android_env/ 2>/dev/null
```

If upstream updated android_env, replace it too. The proto definitions must match.

### Phase 6: Check Server Import Compatibility (~15 min)

Verify our custom server (`RL4AndroidWorld/server/env.py`) still imports correctly from the updated android_world:

```python
# These imports must still work:
from android_world.env import env_launcher, json_action, adb_utils
from android_world import registry, suite_utils
```

Check for renamed modules, moved functions, or changed signatures.

### Phase 7: Rebuild Docker Images (~20 min)

```bash
cd /shared/ligu/projects/SkyRL-AndriodWorld/docker/android/

# Rebuild base image
docker build -t androidworld:v10 \
    -f Dockerfile \
    ../../aw_g_original/docker_env/

# Rebuild layer image with our patches
# First update FROM in Dockerfile.full_adb_agent to androidworld:v10
docker build -t androidworld:v10-full \
    -f Dockerfile.full_adb_agent .
```

### Phase 8: Smoke Test (~10 min)

```bash
# Start single container
docker run -d --name test_aw_v10 \
    -e ENV_ID=999 -e SERVER_PORT=5999 \
    --network host \
    androidworld:v10-full

# Health check
curl http://localhost:5999/health

# Reset a simple task
curl -X POST http://localhost:5999/reset \
    -H "Content-Type: application/json" \
    -d '{"seed": 7, "options": {"task_index": 0}}'

# Run an ADB command
curl -X POST http://localhost:5999/step_adb \
    -H "Content-Type: application/json" \
    -d '{"command": "adb shell input tap 540 960", "thought": "test"}'

# Cleanup
docker stop test_aw_v10 && docker rm test_aw_v10
```

### Phase 9: Validate with Rule-Based Verifier (~2 hours)

This is the critical validation step. Run our 87-task verifier against the new image:

```bash
# Update broker to use new image
# In pool_broker startup, change --docker-image to androidworld:v10-full

# Run verifier
cd skyrl-agent/examples/run_claude_sdk/
python verify_all_71_tasks.py \
    --broker-url http://localhost:9100 \
    --pool-size 16 \
    --output verify_v10_results.json
```

**Expected regressions and fixes:**

| Task Area | Potential Issue | Fix |
|-----------|----------------|-----|
| SMS tasks (68) | `app_names` now includes clipper → different init state | Adjust solver if SMS app state changed |
| Expense/Recipe cross-app | Markor now in `app_names` → gets snapshot-restored | Solvers should still work (we use ADB directly) |
| Clock tasks | `clear_app_data` replaces our hardcoded taps | Should be more reliable, not less |
| IR tasks | Calendar ground truth fix | May need to re-check answer extraction |
| Browser tasks | Chrome data now cleared | Solvers create state fresh, should be fine |

### Phase 10: Agent Benchmark Comparison (~1 hour)

Run a small A/B comparison (10 tasks) with old vs new image:

```bash
# Old image (current)
python run_claude_cli.py \
    --broker-url http://localhost:9100 \
    --pool-size 5 --max-instances 10 \
    --model claude-opus-4-6 \
    --output results/comparison_v8/results.jsonl

# New image (after broker restart with v10)
python run_claude_cli.py \
    --broker-url http://localhost:9100 \
    --pool-size 5 --max-instances 10 \
    --model claude-opus-4-6 \
    --output results/comparison_v10/results.jsonl
```

### Phase 11: Deploy (~15 min)

1. Update broker startup script to use `androidworld:v10-full`
2. Update `container_manager.py` default image name if hardcoded
3. Update any YAML configs that reference image names
4. Full 71-task benchmark run to establish new baseline

## 5. What NOT to Change

| Component | Reason |
|-----------|--------|
| `docker/android/server/server.py` | Our custom `/step_adb` endpoint — not in upstream |
| `docker/android/server/env.py` | Our ADB port support — not in upstream |
| `docker/android/entrypoint.sh` | Our startup flow with per-container ADB ports |
| `skyrl-agent/` (all host code) | HTTP-only communication — no android_world dependency |
| `verify_all_71_tasks.py` | May need minor solver fixes, but framework stays |
| `RL4AndroidWorld/server/` | Our custom server, separate from android_world package |

## 6. Rollback Plan

If the upgrade causes unexpected issues:

1. **Image-level rollback**: Just switch broker back to `androidworld:v9` (or `v8-full`). No code changes needed.
2. **Code-level rollback**: `mv android_world_2024 android_world` to restore the backup.
3. **Partial rollback**: Cherry-pick specific upstream fixes (e.g., SMS field name fix) without taking the full upgrade.

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| New deps break Docker build | Medium | Low | Check requirements.txt diff before building |
| Server import breakage | Low | High | Verify imports in Phase 6 before Docker build |
| Solver regressions | Medium | Medium | 87-task verifier catches all issues |
| android_env proto mismatch | Low | High | Replace android_env if upstream updated it |
| Registry task indexing changes | Medium | Medium | Our JSONL uses task names, not indices |
| Performance regression (longer sleeps) | Low | Low | Upstream increased some sleeps for reliability |

## 8. Success Criteria

- [ ] Docker image builds successfully
- [ ] Container health check passes
- [ ] `/reset`, `/step`, `/step_adb` endpoints work
- [ ] 87-task verifier: ≥85/87 pass (allow 2 regressions to investigate)
- [ ] No import errors in container logs
- [ ] 10-task agent A/B: new image success rate ≥ old image

## 9. Timeline

| Phase | Duration | Dependency |
|-------|----------|------------|
| 1-2: Pull source + identify patches | 45 min | None |
| 3-5: Replace code + check compat | 45 min | Phase 2 |
| 6-7: Server check + Docker rebuild | 35 min | Phase 5 |
| 8: Smoke test | 10 min | Phase 7 |
| 9: Rule-based validation | 2 hours | Phase 8 |
| 10: Agent A/B comparison | 1 hour | Phase 9 |
| 11: Deploy | 15 min | Phase 10 |
| **Total** | **~5 hours** | |

Most time is spent on validation (Phases 9-10), which can run unattended.
