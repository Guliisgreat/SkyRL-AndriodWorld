# Thin Wrapper Architecture: AndroidWorld as Off-the-Shelf Dependency

**Date:** 2026-03-10
**Branch:** TBD (`refactor/cc-androidworld-pip-dependency`)
**Status:** Proposed
**Author:** Li (generated with Claude Code)
**Supersedes:** `androidworld_evaluator_upgrade_plan.md` (fork-based upgrade approach)

## 1. Problem

We maintain a full fork of `google-research/android_world` (146 files, ~50K lines) and `google-deepmind/android_env` inside our repo. Out of 146 android_world files, **only 1 is modified** (`registry.py` — adds EASY/MEDIUM/HARD task tier filtering). Yet every upstream update requires manual diffing, merging, and regression testing.

Our current fork has drifted from upstream (2024 vs 2026) with 35+ missed bug fixes, reliability improvements, and evaluation logic corrections. The manual upgrade process documented in `androidworld_evaluator_upgrade_plan.md` takes ~5 hours and must be repeated every time upstream changes.

## 2. Goal

Treat `android_world` and `android_env` as **pip-installed dependencies** (pinned to a specific commit). All customizations live in our own thin wrapper layer. Upgrading becomes: change a commit hash, rebuild Docker, run verifier.

## 3. Current vs Proposed Architecture

### Current: Forked Copy Baked into Docker

```
aw_g_original/docker_env/RL4AndroidWorld/
├── android_world/          ← FULL COPY in our repo (146 files, 1 modified)
├── android_env/            ← FULL COPY in our repo (unmodified)
├── server/                 ← Our custom code (wrapper)
│   ├── env.py              ← Gymnasium wrapper + monkey-patches
│   ├── server.py           ← FastAPI endpoints
│   └── logger_config.py
├── entrypoint.sh
└── requirements.txt

docker/android/
├── Dockerfile              ← COPY RL4AndroidWorld → pip install -e .
├── Dockerfile.full_adb_agent
├── server/                 ← Patched server overlay
│   ├── env.py              ← ADB port patch + screenshot skip
│   ├── server.py           ← Unified /step + /step_adb
│   └── server_adb.py       ← /step_adb implementation
└── entrypoint.sh

# Dockerfile flow:
COPY RL4AndroidWorld /data/RL4AndroidWorld
RUN cd android_env && pip install -e .
RUN cd android_world && pip install -r requirements.txt && pip install -e .
```

**Problems:**
- 146 files copied into repo that we don't own or modify
- 1 file modified (`registry.py`) — needle in a haystack
- No version tracking — which upstream commit are we based on?
- Upgrade = manual diff of 146 files
- Two copies of server code (`aw_g_original/server/` and `docker/android/server/`)

### Proposed: Pip Install + Thin Wrapper

```
docker/android/
├── Dockerfile              ← pip install from GitHub (pinned commit)
├── requirements.txt        ← android-world + android-env pinned versions
├── skyrl_server/           ← Our code only (~1200 lines, 5 files)
│   ├── __init__.py
│   ├── env.py              ← Gymnasium wrapper (existing, cleaned up)
│   ├── server.py           ← FastAPI endpoints (existing, unified)
│   ├── registry_ext.py     ← NEW: task tier filtering (extracted from fork)
│   ├── patches.py          ← NEW: runtime monkey-patches (extracted from env.py)
│   └── logger_config.py
├── entrypoint.sh
└── .android/               ← Android SDK data (symlink or COPY)

# Dockerfile flow:
RUN pip install -r requirements.txt    ← installs android_world + android_env
COPY skyrl_server/ /data/skyrl_server/  ← only our code
```

**Benefits:**
- Zero upstream files in our repo
- Version explicitly pinned via commit hash
- Upgrade = change hash + rebuild + verify
- Clear separation: upstream code vs our code
- Single source of truth for server code

## 4. Customization Audit

Every piece of custom code classified:

### 4.1 WRAPPER — Uses android_world/android_env as Library (No Changes Needed)

| File | Lines | What It Does |
|------|-------|-------------|
| `server.py` | 420 | FastAPI endpoints: `/reset`, `/step`, `/step_adb`, `/health` |
| `server_adb.py` | 158 | Raw ADB command execution via subprocess |
| `logger_config.py` | 33 | Logging setup |

These files import from android_world but never modify its internals:
```python
from android_world.env import env_launcher, json_action, adb_utils
from android_world import registry, suite_utils
```

**Action:** Keep as-is. These imports target stable public APIs.

### 4.2 MONKEY-PATCHES — Runtime Patches Applied at Import Time

| Patch | Location | Why Needed |
|-------|----------|-----------|
| ADB port override | `env.py:28-58` | Per-container ADB ports in host-network mode |
| Screenshot skip | `env.py:61-81` | Performance: skip expensive image capture |

These are already implemented correctly — they patch at runtime without modifying source:
```python
# Current pattern (already correct):
original_fn = android_world_controller.get_controller
def patched_fn(*args, **kwargs):
    kwargs["adb_server_port"] = int(os.environ.get("ADB_SERVER_PORT", 5037))
    return original_fn(*args, **kwargs)
android_world_controller.get_controller = patched_fn
```

**Action:** Extract to `patches.py` for clarity. No behavior change.

### 4.3 FORK — Modified Upstream Files (Must Be Extracted)

| File | What's Modified | Extractable? |
|------|----------------|-------------|
| `registry.py` | Added EASY/MEDIUM/HARD task tier filtering | Yes — pure data filtering |

This is the **only file** we modified in android_world. The modification adds ~80 lines of task list filtering:
```python
# Current (in forked registry.py):
EASY_TASKS = ["SimpleCalendarDeleteEvents", "ContactsAddContact", ...]
ANDROID_EASY = {k: v for k, v in ANDROID_TASK_REGISTRY.items() if k in EASY_TASKS}
```

**Action:** Extract to `registry_ext.py` in our wrapper. Import upstream registry, filter externally.

## 5. New File Designs

### 5.1 `requirements.txt` — Version Pinning

```
# AndroidWorld dependencies — pinned to specific commits for reproducibility
# To upgrade: change the commit hash, rebuild Docker image, run 87-task verifier
android-env @ git+https://github.com/google-deepmind/android_env.git@COMMIT_HASH_HERE
android-world @ git+https://github.com/google-research/android_world.git@COMMIT_HASH_HERE

# Server dependencies
gymnasium==1.1.1
uvicorn
fastapi
```

**Upgrade workflow:**
```bash
# 1. Find latest upstream commit
git ls-remote https://github.com/google-research/android_world.git HEAD

# 2. Update hash in requirements.txt

# 3. Rebuild
docker build -t androidworld:2026 .

# 4. Verify
python verify_all_71_tasks.py --broker-url ... --output verify_v11.json
```

### 5.2 `registry_ext.py` — Task Tier Filtering (Extracted from Fork)

```python
"""
Task tier filtering for AndroidWorld tasks.

Provides EASY/MEDIUM/HARD subsets of the upstream ANDROID_TASK_REGISTRY
without modifying the upstream registry.py.
"""
from android_world.registry import TaskRegistry

# Task difficulty tiers (curated by our team)
EASY_TASK_NAMES = [
    "SimpleCalendarDeleteEvents",
    "ContactsAddContact",
    "ContactsAddContactDraft",
    "SimpleSmsSendSms",
    # ...
]

MEDIUM_TASK_NAMES = [
    "MarkorCreateNote",
    "MarkorCreateFolder",
    "ExpenseDeleteMultiple",
    # ...
]

HARD_TASK_NAMES = [
    "ExpenseAddMultipleFromMarkor",
    "RecipeAddMultipleRecipesFromMarkor",
    "RecipeAddMultipleRecipesFromImage",
    # ...
]

# Families available via get_registry()
_TIER_MAP = {
    "android_easy": EASY_TASK_NAMES,
    "android_medium": MEDIUM_TASK_NAMES,
    "android_hard": HARD_TASK_NAMES,
    "android_easy_medium": EASY_TASK_NAMES + MEDIUM_TASK_NAMES,
    "android_easy_medium_hard": EASY_TASK_NAMES + MEDIUM_TASK_NAMES + HARD_TASK_NAMES,
}


def get_registry(family: str = "android_world") -> TaskRegistry:
    """Get a task registry, with support for custom difficulty tiers.

    Wraps upstream registry.get_registry() and adds our custom tier filtering.

    Args:
        family: "android_world" for full upstream registry, or
                "android_easy", "android_medium", "android_hard",
                "android_easy_medium", "android_easy_medium_hard".

    Returns:
        TaskRegistry with the requested task subset.
    """
    from android_world import registry as upstream_registry

    if family in _TIER_MAP:
        full = upstream_registry.get_registry("android_world")
        allowed = set(_TIER_MAP[family])
        return {k: v for k, v in full.items() if k in allowed}

    # Fall through to upstream for all standard families
    return upstream_registry.get_registry(family)
```

### 5.3 `patches.py` — Runtime Monkey-Patches

```python
"""
Runtime patches for android_world/android_env.

Applied once at server startup. Each patch is idempotent and isolated.
All patches target stable internal APIs — if an upgrade breaks a patch,
it will fail loudly at import time (not silently at runtime).
"""
import os
import logging

logger = logging.getLogger(__name__)


def patch_adb_port():
    """Override ADB server port for per-container host-network mode.

    android_world hardcodes ADB port 5037. In our multi-container setup,
    each container uses a unique port (ADB_SERVER_PORT env var).
    """
    adb_port = os.environ.get("ADB_SERVER_PORT")
    if not adb_port:
        return

    adb_port = int(adb_port)
    from android_world.env import android_world_controller

    _original = android_world_controller.get_controller

    def _patched(*args, **kwargs):
        kwargs["adb_server_port"] = adb_port
        return _original(*args, **kwargs)

    android_world_controller.get_controller = _patched
    logger.info(f"Patched ADB server port to {adb_port}")


def patch_skip_screenshot():
    """Skip screenshot capture when ENV_SKIP_SCREENSHOT=true.

    Screenshots are expensive (~200ms each) and unnecessary when
    observations are consumed as text (accessibility tree only).
    """
    if os.environ.get("ENV_SKIP_SCREENSHOT", "").lower() not in ("true", "1"):
        return

    from android_env.components import coordinator

    _original = coordinator.Coordinator._gather_simulator_signals

    def _patched(self):
        result = _original(self)
        # Replace pixel array with minimal 1x1 placeholder
        import numpy as np
        result["pixels"] = np.zeros((1, 1, 3), dtype=np.uint8)
        return result

    coordinator.Coordinator._gather_simulator_signals = _patched
    logger.info("Patched screenshot capture to skip (ENV_SKIP_SCREENSHOT=true)")


def apply_all():
    """Apply all patches. Call once at server startup."""
    patch_adb_port()
    patch_skip_screenshot()
```

### 5.4 Updated `env.py` — Simplified

```python
# At the top of env.py, replace inline patches with:
from skyrl_server.patches import apply_all as apply_patches
apply_patches()

# Replace registry import:
# BEFORE: from android_world import registry
# AFTER:  from skyrl_server.registry_ext import get_registry
```

The rest of `env.py` (gymnasium wrapper, emulator lifecycle, etc.) stays unchanged — it already uses android_world as a library.

### 5.5 Updated `Dockerfile`

```dockerfile
FROM ubuntu:22.04

# ... base setup (Android SDK, emulator, etc.) ...

# Install android_world + android_env from upstream (pinned)
COPY requirements.txt /data/requirements.txt
RUN pip install -r /data/requirements.txt

# Install our thin wrapper only
COPY skyrl_server/ /data/skyrl_server/
COPY entrypoint.sh /data/entrypoint.sh

# ... emulator setup, entrypoint, etc. ...
```

**Layer caching benefit:** The `pip install` layer is cached unless `requirements.txt` changes. Our code changes (frequent) only invalidate the `COPY skyrl_server/` layer.

## 6. Migration Plan

### Phase 1: Extract Customizations (No Behavior Change)

1. Create `docker/android/skyrl_server/` directory
2. Move `docker/android/server/*` → `docker/android/skyrl_server/`
3. Create `registry_ext.py` — extract task tier lists from forked `registry.py`
4. Create `patches.py` — extract monkey-patches from `env.py`
5. Update `env.py` imports to use `registry_ext` and `patches`
6. Update `server.py` imports if needed
7. **Test:** Rebuild image, run verifier — must get identical results

### Phase 2: Switch to Pip Install

1. Identify current upstream commit that matches our fork base
2. Create `docker/android/requirements.txt` with pinned commit hashes
3. Update `Dockerfile`:
   - Remove `COPY RL4AndroidWorld /data/RL4AndroidWorld`
   - Remove `RUN cd android_env && pip install -e .`
   - Remove `RUN cd android_world && pip install -e .`
   - Add `COPY requirements.txt && pip install -r requirements.txt`
   - Change `COPY skyrl_server/ /data/skyrl_server/`
4. **Test:** Rebuild image, run verifier

### Phase 3: Upgrade to Latest Upstream

1. Update commit hashes in `requirements.txt` to latest upstream
2. Rebuild image
3. Run 87-task verifier — fix any regressions
4. Run 10-task agent A/B comparison

### Phase 4: Cleanup

1. **Keep** `aw_g_original/docker_env/RL4AndroidWorld/android_world/` and `android_env/` in the repo as reference copies — useful for offline diffing, grep, and understanding evaluator internals without cloning upstream
2. Delete `docker/android/server/` (replaced by `skyrl_server/`)
3. Update any scripts referencing old paths
4. Mark `androidworld_evaluator_upgrade_plan.md` as superseded

## 7. Upgrade Workflow (Post-Migration)

After migration, upgrading android_world becomes a 3-step process:

```bash
# Step 1: Update commit hash
cd docker/android
# Edit requirements.txt — change COMMIT_HASH_HERE to new hash
vim requirements.txt

# Step 2: Rebuild
docker build -t androidworld:2026 -f Dockerfile .

# Step 3: Verify
python verify_all_71_tasks.py \
    --broker-url http://localhost:9100 \
    --output verify_v11.json
```

**Time:** ~30 min (build + verify), down from ~5 hours for the fork-based approach.

If verification fails, the fix is localized:
- Import error → update import path in `env.py` or `patches.py`
- Patch target moved → update monkey-patch in `patches.py`
- Registry API changed → update `registry_ext.py`
- Solver regression → fix specific solver in `verify_all_71_tasks.py`

## 8. Directory Structure (Final State)

```
docker/android/
├── Dockerfile                  ← pip install from requirements.txt
├── requirements.txt            ← android-world + android-env pinned commits
├── skyrl_server/               ← Our code only (~1200 lines)
│   ├── __init__.py
│   ├── env.py                  ← Gymnasium wrapper (cleaned up)
│   ├── server.py               ← FastAPI endpoints (unified)
│   ├── server_adb.py           ← /step_adb implementation
│   ├── registry_ext.py         ← Task tier filtering
│   ├── patches.py              ← Runtime monkey-patches
│   └── logger_config.py        ← Logging setup
├── entrypoint.sh               ← Container startup
└── .android/                   ← Android SDK data

# KEPT in repo as reference (not used by Docker build):
aw_g_original/docker_env/RL4AndroidWorld/
├── android_world/              ← 2024 fork — kept for offline diffing and grep
├── android_env/                ← 2024 copy — kept for reference
└── server/                     ← Legacy server — kept for reference

# DELETED from repo:
# docker/android/server/        (replaced by skyrl_server/)
```

## 9. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Upstream removes/renames public API we import | Low | High | Pin to exact commit; imports are stable (`env_launcher`, `registry`, `suite_utils`) |
| `pip install` from GitHub slower than COPY | Low | Low | Docker layer caching; only rebuilds when hash changes |
| Monkey-patch target moves in new version | Medium | Medium | Patches are isolated in `patches.py`; fail loudly at import |
| android_env proto version mismatch | Low | High | Pin both packages to compatible commits |
| `android-world` package name conflict on PyPI | Low | Low | Install from GitHub URL, not PyPI name |
| `.android/` SDK data still needs COPY | N/A | N/A | SDK data is separate from android_world package; unchanged |

## 10. What Does NOT Change

| Component | Why |
|-----------|-----|
| `skyrl-agent/` (all host code) | HTTP-only communication — no android_world dependency |
| `verify_all_71_tasks.py` | Talks to containers via HTTP — no android_world imports |
| `container_manager.py` | Manages Docker containers — no android_world imports |
| `pool_broker.py` | Container pool orchestration — no android_world imports |
| `entrypoint.sh` | Starts emulator + server — no android_world imports |
| Agent code (claude_sdk, t3a, etc.) | HTTP clients — no android_world imports |

## 11. Success Criteria

- [ ] `docker/android/skyrl_server/` contains all our custom code (~5 files, ~1200 lines)
- [ ] Original android_world and android_env kept in repo as reference (not used by Docker build)
- [ ] `requirements.txt` pins both packages to explicit commit hashes
- [ ] Docker image builds successfully from pip install
- [ ] 87-task verifier passes (>=85/87)
- [ ] Upgrading android_world takes <30 min (change hash + rebuild + verify)
- [ ] No changes needed in any host-side code (`skyrl-agent/`)
