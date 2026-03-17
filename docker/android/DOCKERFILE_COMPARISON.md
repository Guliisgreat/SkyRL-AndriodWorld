# AndroidWorld Docker Images Comparison

This document compares all Docker images for AndroidWorld containers.

---

## Image Hierarchy

```
ubuntu:22.04
  └── androidworld:v8              (base image, forked android_world)
        ├── androidworld:v9         (ADB port fix only)
        ├── androidworld-adb:v8     (/step_adb only)
        ├── androidworld:full_adb_agent  (all features, forked)
        └── androidworld:2026       ← RECOMMENDED (upstream packages)
```

---

## Quick Comparison

| Feature | v8 (base) | v9 | adb:v8 | full_adb_agent | **2026** |
|---|---|---|---|---|---|
| Dockerfile | `Dockerfile` | `Dockerfile.v9` | `Dockerfile.adb` | `Dockerfile.full_adb_agent` | **`Dockerfile.2026`** |
| android_world source | Forked | Forked | Forked | Forked | **Upstream pip** |
| Emulator + env | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/health`, `/reset`, `/step` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/step_adb` (ADB commands) | ❌ | ❌ | ✅ | ✅ | ✅ |
| Per-container ADB port | ❌ | ✅ | ❌ | ✅ | ✅ |
| `ui_elements` in observations | ❌ | ❌ | ❌ | ✅ | ✅ |
| `ENV_SKIP_SCREENSHOT` support | ❌ | ❌ | ❌ | ❌ | ✅ |
| Host network (16+ containers) | ❌ (5 max) | ✅ | ❌ (5 max) | ✅ | ✅ |
| GUI agent compatible | ✅ | ✅ | ✅ | ✅ | ✅ |
| ADB agent compatible | ❌ | ❌ | ✅ | ✅ | ✅ |
| A11y tree input | ❌ | ❌ | ❌ | ✅ | ✅ |
| v8 task ordering (JSONL compat) | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Detailed Descriptions

### `androidworld:v8` — Base Image

**Dockerfile:** `Dockerfile`
**Built from:** `ubuntu:22.04`

The foundation image. Installs Python 3.11, Android SDK, emulator, `android_env`, and `android_world` libraries. Runs a FastAPI server with `/health`, `/reset`, and `/step` endpoints.

**Limitations:**
- ADB daemon always uses port 5037 — only ~5 containers work in parallel with host networking
- No `/step_adb` endpoint — cannot run ADB agent
- No `ui_elements` in observations

**Build:**
```bash
cd docker/android && docker build -t androidworld:v8 .
```

---

### `androidworld:v9` — ADB Port Fix

**Dockerfile:** `Dockerfile.v9`
**Built from:** `androidworld:v8`

Fixes the ADB port collision issue for host networking. Patches `entrypoint.sh` to start ADB on `ADB_SERVER_PORT` (unique per container) and `env.py` to monkey-patch `android_world` to use that port.

**What it adds over v8:**
- Per-container ADB daemon on unique port
- 16+ containers in parallel with host networking

**What it lacks:**
- No `/step_adb` endpoint
- No `ui_elements` in observations

**Build:**
```bash
docker build -f docker/android/Dockerfile.v9 -t androidworld:v9 docker/android
```

---

### `androidworld-adb:v8` — ADB Command Agent

**Dockerfile:** `Dockerfile.adb`
**Built from:** `androidworld:v8`

Adds the `/step_adb` endpoint for raw ADB command execution. Uses a separate `entrypoint_adb.sh` that runs `server_adb.py` instead of `server.py`.

**What it adds over v8:**
- `POST /step_adb` — accepts raw ADB commands, validates against whitelist/blocklist, executes via subprocess
- ADB agent support

**What it lacks:**
- No per-container ADB port fix — only ~5 containers with host networking
- No `ui_elements` in observations

**Build:**
```bash
docker build -f docker/android/Dockerfile.adb -t androidworld-adb:v8 docker/android
```

---

### `androidworld:full_adb_agent` — Unified Image (Recommended)

**Dockerfile:** `Dockerfile.full_adb_agent`
**Built from:** `androidworld:v8`

Combines all features into a single image. One server process exposes all endpoints. Observations always include `ui_elements` (a11y tree). Per-container ADB port for host networking.

**What it adds:**
- Everything from v9 (ADB port fix)
- Everything from adb:v8 (`/step_adb` endpoint)
- `ui_elements` array in every observation (a11y tree data)
- Single unified `server.py` — no separate `server_adb.py`

**Supports all 4 agent modes:**

```
                    Output Mode
                    ─────────────────────────────────
                    GUI action (/step)    ADB command (/step_adb)
Input Mode         ┌─────────────────┬─────────────────────────┐
Screenshot only    │  AndroidAgent   │  AndroidADBAgent        │
                   ├─────────────────┼─────────────────────────┤
Screenshot +       │  AndroidAgent   │  AndroidADBAgent        │
a11y tree          │  + use_a11y     │  + use_a11y             │
                   └─────────────────┴─────────────────────────┘
```

The container is mode-agnostic — it always returns both screenshot and `ui_elements`. The agent decides which to use via config.

**Build:**
```bash
docker build -f docker/android/Dockerfile.full_adb_agent \
    -t androidworld:full_adb_agent docker/android
```

---

### `androidworld:2026` — Upstream Thin Wrapper (Recommended)

**Dockerfile:** `Dockerfile.2026`
**Built from:** `androidworld:v8`

Replaces the forked `android_world` / `android_env` libraries with upstream pip packages (pinned to specific commits). Uses a clean `skyrl_server/` wrapper that delegates to the upstream API. This decouples our infrastructure from upstream changes and makes upgrades trivial.

**Key differences from `full_adb_agent`:**
- **Upstream packages**: `android_world` and `android_env` installed from GitHub via pip, not forked copies
- **`registry_ext.py`**: Maintains v8-compatible task ordering so existing JSONL data files (positional `task_id`) work unchanged with upstream's alphabetical registry
- **`ENV_SKIP_SCREENSHOT`**: Can skip screenshot capture for ADB-only agents (saves ~6s/step)
- **`patches.py`**: Runtime monkey-patches for ADB port override without modifying upstream source
- **Cleaner codebase**: `skyrl_server/` is a self-contained module (~7 files) with no coupling to our agent code

**Supports all endpoints and agent modes** — same as `full_adb_agent`.

**Build:**
```bash
cd docker/android
docker build -f Dockerfile.2026 -t androidworld:2026 .
```

---

## Observation Format

### v8 / v9 / adb:v8

```json
{
    "image": "<base64>",
    "image_shape": [1920, 1080, 3],
    "image_dtype": "uint8",
    "task": "Open the contacts app..."
}
```

### full_adb_agent / 2026

```json
{
    "image": "<base64>",
    "image_shape": [1920, 1080, 3],
    "image_dtype": "uint8",
    "task": "Open the contacts app...",
    "ui_elements": [
        {
            "text": "Settings",
            "content_description": "",
            "class_name": "android.widget.TextView",
            "clickable": true,
            "bbox_pixels": {"x_min": 100, "x_max": 300, "y_min": 200, "y_max": 250}
        }
    ]
}
```

When `ENV_SKIP_SCREENSHOT=True` (2026 only), `image`, `image_shape`, and `image_dtype` are omitted from the response.
```

---

## Server Endpoints

### v8 / v9

| Endpoint | Method |
|---|---|
| `/health` | GET |
| `/deep_health` | GET |
| `/reset` | POST |
| `/step` | POST |
| `/env_log` | POST |
| `/get_n_tasks` | GET |

### adb:v8

Same as v8 plus:

| Endpoint | Method |
|---|---|
| `/step_adb` | POST |

### full_adb_agent / 2026

All endpoints from both:

| Endpoint | Method |
|---|---|
| `/health` | GET |
| `/deep_health` | GET |
| `/reset` | POST |
| `/step` | POST |
| `/step_adb` | POST |
| `/env_log` | POST |
| `/get_n_tasks` | GET |

---

## Migration Guide

To switch from any existing image to `androidworld:2026` (recommended):

1. Build the image:
   ```bash
   cd docker/android
   docker build -f Dockerfile.2026 -t androidworld:2026 .
   ```

2. Update YAML config:
   ```yaml
   env:
     docker_image: androidworld:2026
     use_host_network: true
   ```

3. For ADB-only agents (no screenshots needed), add `--skip-screenshot` to the broker:
   ```bash
   python -m skyrl_agent.runtime.android.pool_broker \
       --docker-image androidworld:2026 --skip-screenshot
   ```
   **Important:** VLM agents (UI-TARS, Qwen2-VL) require screenshots — do NOT use `--skip-screenshot` with them.

No code changes needed on the agent side — `RuntimeClient` supports both `step()` and `step_adb()`.

### Upgrading from `full_adb_agent` to `2026`

The API is identical. Just change `docker_image` in your YAML. The only behavioral difference is that `2026` uses upstream `android_world` packages, so task class ordering follows our `registry_ext.py` (which preserves v8 ordering for JSONL compatibility).
