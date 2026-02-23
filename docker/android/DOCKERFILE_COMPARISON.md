# AndroidWorld Docker Images Comparison

This document compares all Docker images for AndroidWorld containers.

---

## Image Hierarchy

```
ubuntu:22.04
  └── androidworld:v8              (base image)
        ├── androidworld:v9         (ADB port fix only)
        ├── androidworld-adb:v8     (/step_adb only)
        └── androidworld:full_adb_agent  ← RECOMMENDED (all features)
```

---

## Quick Comparison

| Feature | v8 (base) | v9 | adb:v8 | full_adb_agent |
|---|---|---|---|---|
| Dockerfile | `Dockerfile` | `Dockerfile.v9` | `Dockerfile.adb` | `Dockerfile.full_adb_agent` |
| Emulator + env | ✅ | ✅ | ✅ | ✅ |
| `/health`, `/reset`, `/step` | ✅ | ✅ | ✅ | ✅ |
| `/step_adb` (ADB commands) | ❌ | ❌ | ✅ | ✅ |
| Per-container ADB port | ❌ | ✅ | ❌ | ✅ |
| `ui_elements` in observations | ❌ | ❌ | ❌ | ✅ |
| Host network (16+ containers) | ❌ (5 max) | ✅ | ❌ (5 max) | ✅ |
| GUI agent compatible | ✅ | ✅ | ✅ | ✅ |
| ADB agent compatible | ❌ | ❌ | ✅ | ✅ |
| A11y tree input | ❌ | ❌ | ❌ | ✅ |

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

### full_adb_agent

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

### full_adb_agent

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

To switch from any existing image to `androidworld:full_adb_agent`:

1. Build the image:
   ```bash
   docker build -f docker/android/Dockerfile.full_adb_agent \
       -t androidworld:full_adb_agent docker/android
   ```

2. Update YAML config:
   ```yaml
   env:
     docker_image: androidworld:full_adb_agent
     use_host_network: true
   ```

No code changes needed on the agent side — `RuntimeClient` now supports both `step()` and `step_adb()`.
