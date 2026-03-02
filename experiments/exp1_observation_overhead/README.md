# Experiment 1: Per-Step Observation Overhead

Micro-benchmark measuring the wall-clock cost of three observation paradigms:

| Category | Conditions |
|---|---|
| **Screenshot** | `screenshot_png`, `screenshot_raw` |
| **A11y Tree** | `a11y_uiautomator_dump`, `a11y_dumpsys` |
| **Direct ADB** | `adb_getprop`, `adb_wm_size`, `adb_input_tap` |

Each condition is measured across 3 app screens × 100 repetitions (= 2,100 data points total).

## Quick Start

```bash
# From repo root
cd /shared/ligu/projects/SkyRL-AndriodWorld

# Option A: auto-create a Docker container (default)
python experiments/exp1_observation_overhead/run_benchmark.py --host-network

# Option B: use an already-running emulator
python experiments/exp1_observation_overhead/run_benchmark.py --adb-serial emulator-5574

# Analyze results and generate charts
python experiments/exp1_observation_overhead/analyze_results.py
```

## Options

| Flag | Default | Description |
|---|---|---|
| `--adb-serial` | *(none)* | Skip container creation; use this device serial directly |
| `--host-network` | off | Use host networking when creating a container |
| `--image` | `androidworld:full_adb_agent` | Docker image for the emulator container |
| `--base-env-id` | `400` | Starting env_id (avoids port collision with running containers) |
| `--initial-wait` | `30` | Seconds to wait for emulator boot |
| `--reps` | `100` | Number of measurement repetitions |
| `--warmup` | `5` | Number of warmup repetitions (discarded) |

## Output

All outputs are written to `results/`:

| File | Description |
|---|---|
| `raw_timings.csv` | One row per measurement (condition, screen, rep, wall_clock_s, success) |
| `summary_stats.csv` | Per-condition aggregates (mean, std, median, 95% CI) |
| `observation_overhead.png` | Bar chart with 95% CI error bars |
| `observation_overhead.pdf` | Same chart in vector format |

## Prerequisites

- Docker with KVM support
- `androidworld:full_adb_agent` image (or specify `--image`)
- Python packages: `numpy`, `pandas`, `matplotlib` (for analysis)
