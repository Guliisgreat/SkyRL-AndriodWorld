# MobileWorld vs AndroidWorld: Docker Architecture Comparison

**Date**: 2026-03-29

## Architecture Diagrams

### MobileWorld Container (ghcr.io/tongyi-mai/mobile_world:latest)

```
┌─────────────────────────────────────────────────────────────────────┐
│  MobileWorld Container (Bridge Network)                              │
│  Ports: 6800(server) 5556(adb) 7860(viewer) 5800(vnc)              │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Android Emulator (Pixel 8, API 34, x86_64)                  │   │
│  │  Device: emulator-5554                                        │   │
│  │                                                                │   │
│  │  Pre-installed Apps (20):                                      │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │ Chrome   │ │ Gmail    │ │ Calendar │ │ Contacts │        │   │
│  │  │          │ │ (clone)  │ │ (Fossify)│ │ (Google) │        │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │ Messages │ │ Maps     │ │ Camera   │ │ Gallery  │        │   │
│  │  │ (Google) │ │ (Google) │ │          │ │          │        │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │ Mastodon │ │Mattermost│ │ TaoDian  │ │ Clock    │        │   │
│  │  │ (Android)│ │ (Android)│ │ (Mall)   │ │ (Google) │        │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │ Files    │ │ Settings │ │ PDF View │ │ DocReader│        │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │   │
│  │                                                                │   │
│  │  Snapshot: init_state (AVD snapshot for deterministic reset)   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  MobileWorld Server (FastAPI, port 6800)                      │   │
│  │                                                                │   │
│  │  Endpoints:                                                    │   │
│  │  ├── /health          — device health check                   │   │
│  │  ├── /init            — initialize device controller          │   │
│  │  ├── /screenshot      — get device screenshot (base64)        │   │
│  │  ├── /xml             — get UI accessibility tree             │   │
│  │  ├── /step            — execute action (click/type/scroll)    │   │
│  │  ├── /sms             — simulate incoming SMS                 │   │
│  │  ├── /task/list       — list all 201 tasks                    │   │
│  │  ├── /task/init       — init task (snapshot restore + setup)  │   │
│  │  ├── /task/eval       — evaluate task success (rule-based)    │   │
│  │  ├── /task/tear_down  — cleanup after task                    │   │
│  │  ├── /task/goal       — get task description                  │   │
│  │  └── /suite_family/switch — switch task suite                 │   │
│  │                                                                │   │
│  │  SkyRL Adapter (optional, SKYRL_COMPAT=1):                    │   │
│  │  ├── /reset           — teardown + init task                  │   │
│  │  ├── /step_adb        — execute ADB command                   │   │
│  │  └── /deep_health     — emulator responsiveness test          │   │
│  │                                                                │   │
│  │  Task Registry: 201 tasks auto-discovered from definitions/   │   │
│  │  Verifier: 100% rule-based (DB queries, file checks, API)    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌───────────────────────── Docker-in-Docker ───────────────────┐   │
│  │                                                                │   │
│  │  ┌─────────────── Mastodon Stack ──────────────────┐          │   │
│  │  │  nginx (reverse proxy, HTTPS, port 443)          │          │   │
│  │  │  web (Ruby on Rails, Mastodon v4.3.7)            │          │   │
│  │  │  streaming (Node.js WebSocket)                    │          │   │
│  │  │  sidekiq (background jobs)                        │          │   │
│  │  │  PostgreSQL (port 5432, user: postgres)           │          │   │
│  │  │  Redis (port 6379)                                │          │   │
│  │  └──────────────────────────────────────────────────┘          │   │
│  │                                                                │   │
│  │  ┌─────────────── Mattermost Stack ────────────────┐          │   │
│  │  │  Mattermost (Go, port 8065)                      │          │   │
│  │  │  PostgreSQL (port 5433, user: mmuser)             │          │   │
│  │  └──────────────────────────────────────────────────┘          │   │
│  │                                                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Utilities                                                     │   │
│  │  ├── socat (ADB port relay: 5556 → emulator ADB port)        │   │
│  │  ├── noVNC (web-based screen viewer, port 5800)               │   │
│  │  └── Web Viewer (FastHTML, port 7860)                          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### AndroidWorld Container (androidworld:v9)

```
┌─────────────────────────────────────────────────────────────────────┐
│  AndroidWorld Container (Host Network)                               │
│  Ports: ADB=5037+env_id, Server=env_id+assigned                    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Android Emulator (Pixel 6, API 33/34, x86_64)               │   │
│  │  Device: emulator-{5554+env_id*2}                             │   │
│  │                                                                │   │
│  │  Pre-installed Apps (~15, open-source):                        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │ Simple   │ │ Simple   │ │ Simple   │ │ Markor   │        │   │
│  │  │ Calendar │ │ Contacts │ │ SMS      │ │          │        │   │
│  │  │ Pro      │ │ Pro      │ │ Messenger│ │          │        │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │Bluecoins │ │ Joplin   │ │ VLC      │ │ Recipe   │        │   │
│  │  │(Expense) │ │ (Notes)  │ │ (Media)  │ │ Keeper   │        │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │ Chrome   │ │ Clock    │ │ Settings │ │ Files    │        │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                     │   │
│  │  │AudioRec  │ │OpenTracks│ │Tasks.org │                     │   │
│  │  └──────────┘ └──────────┘ └──────────┘                     │   │
│  │                                                                │   │
│  │  No snapshot — tasks use programmatic setup/teardown           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  AndroidWorld Server (Flask/FastAPI)                           │   │
│  │                                                                │   │
│  │  Endpoints:                                                    │   │
│  │  ├── /health          — emulator health check                 │   │
│  │  ├── /deep_health     — emulator responsiveness test          │   │
│  │  ├── /reset           — reset environment for new task        │   │
│  │  └── /step_adb        — execute ADB command, return reward    │   │
│  │                                                                │   │
│  │  Task setup: via android_world Python library (not server)    │   │
│  │  Verifier: Python functions called from host                   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  No Docker-in-Docker (no backend services)                           │
│  No Mastodon, no Mattermost, no Mall app                            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Side-by-Side Comparison

| Feature | AndroidWorld (2026) | MobileWorld |
|---------|-------------------|-------------|
| **Docker Image** | `androidworld:full_adb_agent` (~5GB) | `ghcr.io/tongyi-mai/mobile_world:latest` (~21GB) |
| **Network Mode** | Host (shared namespace) | Bridge (isolated, port-mapped) |
| **Emulator** | Pixel 6, API 33/34 | Pixel 8, API 34 |
| **Total Tasks** | 116 | 201 |
| **Task Types** | GUI-only | GUI-only + User-Interaction + MCP |
| **Apps** | ~15 (open-source: Simple*, Markor, Bluecoins, Joplin, etc.) | ~20 (Google + Mastodon + Mattermost + Mall) |
| **Backend Services** | None (standalone) | Mastodon (6 containers) + Mattermost (2 containers) |
| **Docker-in-Docker** | No | Yes (8 sub-containers for backends) |
| **State Management** | Snapshot restore via `/reset` + gRPC | AVD snapshot restore via `/task/init` |
| **Server Port** | 5000 + 2*env_id (dynamic) | 6800 (configurable via SERVER_PORT) |
| **ADB Port** | 5037 + env_id (host) | 5556 internal, mapped externally (bridge) |
| **gRPC Port** | emulator_port + 3000 | N/A |
| **Verification** | Python functions (host-side) | Rule-based (server-side via /task/eval) |
| **Eval Location** | Host process calls verifier | Container server runs verifier |
| **Server Endpoints** | 7 (/health, /deep_health, /reset, /step, /step_adb, /get_n_tasks, /env_log) | 15+ (task lifecycle, screenshots, XML, SMS, etc.) |
| **Observation** | Screenshot (base64) + UI a11y tree + task text | Screenshot + a11y tree (via /xml) |
| **Orchestration** | Full: PortAllocator → ContainerFactory → ContainerManager → PoolBroker | Lightweight: mw_cli_common.py wrapper |
| **Health Monitoring** | Background async + instant failover with backup pool | None (manual restart) |
| **Failover** | Replace-not-restart with backup containers (<1s) | Manual container restart |
| **Max Parallel** | 27+ (tested, host network) | 8+ (tested, bridge network) |
| **Image Variants** | v8, v9, adb, full_adb_agent, 2026 | latest, skyrl, updated |

## Key Architectural Differences

### 1. Backend Services (Docker-in-Docker)
```
AndroidWorld:                    MobileWorld:
┌──────────┐                    ┌──────────────────────────────┐
│ Emulator │                    │ Emulator                      │
│ + Server │                    │ + Server                      │
│          │                    │ + Docker-in-Docker:           │
│ (no      │                    │   ├── Mastodon (6 services)  │
│  backends│                    │   │   ├── nginx + web        │
│         )│                    │   │   ├── streaming + sidekiq│
│          │                    │   │   ├── PostgreSQL :5432   │
│          │                    │   │   └── Redis :6379        │
│          │                    │   └── Mattermost (2 services)│
│          │                    │       ├── Mattermost :8065   │
└──────────┘                    │       └── PostgreSQL :5433   │
                                └──────────────────────────────┘
```

### 2. Task Lifecycle
```
AndroidWorld:                    MobileWorld:
Host          Container          Host          Container
  │              │                 │              │
  ├─ setup() ──>│                 ├─ /task/init─>│──> snapshot restore
  │  (Python    │                 │              │──> start backends
  │   library)  │                 │              │──> run init hook
  │              │                 │              │
  ├─ /step_adb >│                 ├─ agent runs >│ (direct ADB or
  │  (returns   │                 │  (via CLI    │  /step endpoint)
  │   reward)   │                 │   wrapper)   │
  │              │                 │              │
  ├─ verify() ─>│                 ├─ /task/eval─>│──> run verifier
  │  (host-side │                 │  (server-    │──> DB queries
  │   Python)   │                 │   side eval) │──> file checks
  │              │                 │              │
  ├─ teardown()>│                 ├─/task/tear──>│──> cleanup
  │              │                 │   _down      │──> stop backends
```

### 3. Network & Port Allocation
```
AndroidWorld (Host Network):     MobileWorld (Bridge Network):

Host ──────────────────────     Host ─────────────────────────
│ env0: ADB=5037, srv=X   │    │                              │
│ env1: ADB=5038, srv=X+1 │    │  ┌─ Container 1 ─────────┐  │
│ env2: ADB=5039, srv=X+2 │    │  │ internal: 6800, 5554   │  │
│ ...                      │    │  │ mapped: 6809, 5565     │  │
│ All on host network      │    │  └────────────────────────┘  │
│ Bare `adb` needs -s flag │    │  ┌─ Container 2 ─────────┐  │
│                          │    │  │ internal: 6800, 5554   │  │
│                          │    │  │ mapped: 6816, 5572     │  │
│                          │    │  └────────────────────────┘  │
│                          │    │  Each container isolated     │
└──────────────────────────┘    └──────────────────────────────┘
```

### 4. Container Orchestration Stack
```
AndroidWorld:                           MobileWorld:

┌─────────────────────────────────┐    ┌─────────────────────────────┐
│  ContainerPoolBroker (HTTP)     │    │  (No broker)                │
│  POST /acquire → lease container│    │                             │
│  POST /return  → snapshot reset │    │                             │
│  GET  /status  → pool metrics   │    │                             │
├─────────────────────────────────┤    │                             │
│  HealthMonitor (background)     │    │  (No health monitoring)     │
│  Periodic /health checks        │    │                             │
│  Instant failover w/ backup     │    │                             │
│  Replace-not-restart policy     │    │                             │
├─────────────────────────────────┤    ├─────────────────────────────┤
│  ContainerManager               │    │  mw_cli_common.py           │
│  Creates N containers at start  │    │  Simple HTTP wrappers       │
│  Pool management in memory      │    │  Sequential or threaded     │
│  Auto-replacement on failure    │    │  Manual health checks       │
├─────────────────────────────────┤    ├─────────────────────────────┤
│  ContainerFactory               │    │  `mw env run`  (CLI)        │
│  Docker API container creation  │    │  Docker API launch          │
│  Port allocation (PortAllocator)│    │  Static port assignment     │
│  Health check wait (600s max)   │    │  Ready wait (120s max)      │
├─────────────────────────────────┤    ├─────────────────────────────┤
│  PortAllocator                  │    │  Incremental ports          │
│  server: 5000+2*env_id          │    │  server: 6800+offset        │
│  emulator: 5574+2*env_id (even) │    │  emulator: 5554 (internal)  │
│  adb: 5037+env_id               │    │  adb: 5556 (socat relay)    │
│  grpc: emulator+3000            │    │  viewer: 7860               │
└─────────────────────────────────┘    └─────────────────────────────┘
```

### 5. CLI Solvability (Ground Truth)
```
AndroidWorld:                    MobileWorld:
┌────────────────────────┐      ┌────────────────────────────┐
│ 87 terminal tasks      │      │ 117 GUI-only tasks         │
│ (val_data_seed7_       │      │                            │
│  terminal.jsonl)       │      │ CLI-solvable: 117/117      │
│                        │      │ (100% via ADB + REST API   │
│ Solved via:            │      │  + PostgreSQL + file write) │
│ ├── ADB shell          │      │                            │
│ ├── Content providers   │      │ Solved via:                │
│ ├── am/pm intents      │      │ ├── ADB shell/intents     │
│ └── Settings commands   │      │ ├── Content providers     │
│                        │      │ ├── Mastodon REST API     │
│ No backend APIs        │      │ ├── Mastodon PostgreSQL   │
│ (no Mastodon/MM)       │      │ ├── Mattermost PostgreSQL │
│                        │      │ ├── sentEmail.json write  │
│                        │      │ ├── Mall callback write   │
│                        │      │ ├── Calendar SQLite       │
│                        │      │ ├── GitHub/Weather APIs   │
│                        │      │ └── Alarm DB write        │
└────────────────────────┘      └────────────────────────────┘
```
