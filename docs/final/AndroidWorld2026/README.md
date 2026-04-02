# AndroidWorld Ground Truth — 116 Tasks

Ground truth ADB command trajectories for the AndroidWorld benchmark.
101 tasks are CLI-solvable (87.1% SR); 15 require GUI interaction.

## 1. Ground Truth Reference

**File:** `androidworld_ground_truth_reference.md`

The reference doc covers all 116 tasks organized by app category (System Settings, Contacts, Markor, Broccoli Recipes, Calendar, Pro Expense, SMS, Retro Music, VLC, OsmAnd, Files, etc.).

For each task you will find:

- **Goal** — the exact task instruction given to the agent
- **Status** — PASS, FAIL, or GUI-only
- **Ground Truth Steps** — each step shows:
  - Action type: `bash`, `sql`, `read-file`, `write-file`, or `search`
  - The exact `adb shell` command
  - Command output (when relevant)
- **Verifier** — how `is_successful()` determines reward=1 vs reward=0 (what device state is checked)

Every step is a single ADB command (no shell scripts). The 5 action types are:

| Type | Example |
|------|---------|
| bash | `adb shell am start ...`, `adb shell svc wifi enable`, `adb shell mv ...` |
| sql | `adb shell "sqlite3 /path/db \"SELECT ...;\""` |
| read-file | `adb shell cat /path/to/file` |
| write-file | `adb shell "echo BASE64 \| base64 -d > /path"` |
| search | `adb shell "content query --uri content://... --where ..."` |

## 2. Reproduce with run_ground_truth.py

**File:** `../../skyrl-agent/examples/run_androidworld/run_ground_truth.py`

### Prerequisites

- Pool broker running with `androidworld:2026` containers
- Python with `requests` installed

### Start a broker (if not already running)

```bash
cd skyrl-agent
python -m skyrl_agent.runtime.android.pool_broker \
    --pool-size 16 \
    --docker-image androidworld:2026 \
    --port 9300
```

### Run all 116 tasks

```bash
python skyrl-agent/examples/run_androidworld/run_ground_truth.py \
    --broker-url http://localhost:9300 \
    --pool-size 16
```

### Run specific tasks

```bash
# By task ID
python run_ground_truth.py --broker-url http://localhost:9300 --task-ids 9,33,72

# Custom output directory
python run_ground_truth.py --broker-url http://localhost:9300 --output-dir results/my_run
```

### Output

The runner produces three files in the output directory:

```
results/<run_name>/
  results.jsonl        # Per-task results (task_id, reward, commands, elapsed)
  summary.json         # Aggregate stats (total, success, SR, gui_only)
  atif_trajectories/   # ATIF-v1.6 JSON per task (Harbor-compatible)
    task_000.json
    task_001.json
    ...
    task_115.json
```

## 3. View Trajectories with Harbor Viewer

### Setup Harbor view structure

```bash
python -c "
from harbor.models.job.result import JobResult, JobStats
from harbor.models.trial.result import TrialResult, TrialConfig, VerifierResult
from harbor.models.job.config import JobConfig, AgentConfig, EnvironmentConfig
import json, os, shutil
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

src = 'skyrl-agent/results/GroundTruth_oracle_260401_1945'  # your run dir
view = os.path.join(src, 'harbor_view', 'GroundTruth')
os.makedirs(view, exist_ok=True)

# Write config
config = JobConfig(
    agents=[AgentConfig(name='GroundTruth', model_name='oracle')],
    datasets=[],
    environment=EnvironmentConfig(type='docker'),
)
Path(f'{view}/config.json').write_text(config.model_dump_json(indent=2, exclude_none=True))

# Build trials
now = datetime.now(timezone.utc)
with open(f'{src}/results.jsonl') as f:
    tasks = sorted([json.loads(l) for l in f], key=lambda x: x['task_id'])

trial_results = []
for t in tasks:
    name = f\"task_{t['task_id']:03d}_{t['task_name']}\"
    os.makedirs(f'{view}/{name}/agent', exist_ok=True)
    atif = f\"{src}/atif_trajectories/task_{t['task_id']:03d}.json\"
    if os.path.exists(atif):
        shutil.copy2(atif, f'{view}/{name}/agent/trajectory.json')
    tr = TrialResult(
        id=uuid4(), task_name=t['task_name'], trial_name=name,
        trial_uri=f'file://{view}/{name}',
        task_id={'path': f\"androidworld/{t['task_name']}\"},
        task_checksum='0'*64,
        config=TrialConfig(task={'path': f\"androidworld/{t['task_name']}\"}, max_steps=30, timeout=300),
        agent_info={'name': 'GroundTruth', 'version': '1.0', 'model_name': 'oracle'},
        verifier_result=VerifierResult(rewards={'default': float(t['reward'])}),
        started_at=now, finished_at=now,
    )
    Path(f'{view}/{name}/result.json').write_text(tr.model_dump_json(indent=2, exclude_none=True))
    trial_results.append(tr)

# Write job result
job = JobResult(
    id=uuid4(), started_at=now, finished_at=now,
    n_total_trials=len(tasks),
    stats=JobStats.from_trial_results(trial_results),
    trial_results=trial_results,
)
Path(f'{view}/result.json').write_text(job.model_dump_json(indent=2, exclude_none=True))
print(f'Harbor view: {os.path.dirname(view)}')
"
```

### Launch the viewer

```bash
# On the server
python -c "
from harbor.viewer import create_app
from pathlib import Path
import uvicorn
static = Path('~/.local/lib/python3.13/site-packages/harbor/viewer/static').expanduser()
app = create_app(Path('skyrl-agent/results/GroundTruth_oracle_260401_1945/harbor_view'), static_dir=static)
uvicorn.run(app, host='0.0.0.0', port=9500)
"
```

### Access from local laptop

```bash
# SSH tunnel
ssh -L 9500:localhost:9500 ligu@202.78.161.193

# Open browser
open http://localhost:9500
```

### API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI |
| `GET /api/jobs` | List all jobs |
| `GET /api/jobs/{job}/trials` | List trials in a job |
| `GET /api/jobs/{job}/trials/{trial}/trajectory` | Get ATIF trajectory JSON |
