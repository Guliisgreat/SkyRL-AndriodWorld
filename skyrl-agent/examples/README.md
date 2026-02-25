## Examples

This directory contains runnable examples for multiple tasks. Each section outlines how to set up any required services, prepare datasets, and launch training or inference.

### 1) SWE Training

- Setup remote runtime/server:
  - Refer to the [SkyRL-OpenHands](https://github.com/NovaSky-AI/SkyRL-OpenHands) documentation to set up a remote sandbox server and cache train/eval images.
  - After setup, configure your the remote server URL and API key in the environment file (i.e., `.env`).

- Prepare dataset:
  - Run the dataset preparation script:
    ```bash
    python ./data/swe_data.py --output SWE_DATA_PATH
    ```

- Launch training (modify the corresponding path in the script first):
  - VERL-based:
    ```bash
    bash ./examples/run_verl/verl_oh.sh
    ```
  - SkyRL-Train-based:
    ```bash
    bash ./examples/run_skyrl/skyrl_swe.sh
    ```

- Run inference (demo):
Launch an OpenAI API-compatible serving (e.g., vLLM or similar), then configure the `api_url` in the corresponding YAML (typically under the backend config) to point to your serving endpoint. Then run:
    ```bash
    python ./examples/run_openai/test_vllm_oh_demo.py
    ```

### 2) MemAgent Training

- Prepare dataset:
  ```bash
  python ./data/memagent.py --output-dir MEM_DATA_DIR
  ```

- Configure API:
  - Set the OpenAI API key in the environment file (i.e., `.env`); by default we use GPT-5-nano as the LLM judge for reward calculation.

- Backend note:
  - MemAgent currently supports only the Tinker backend for step-wise training. Set your Tinker API key in the environment file (i.e., `.env`).

- Launch training (modify the corresponding path in the script first):
  ```bash
  bash ./examples/run_tinker/tinker_memagent.sh
  ```

### 3) Deep Research (web_research_hle.sh)

- Quick setup: `uv venv && uv sync`.

- Required `.env`: `WANDB_API_KEY`, `GOOGLE_SEARCH_KEY` (Serper key), `JINA_API_KEYS`, `WEB_SUMMARY_API_BASE`, `WEB_SUMMARY_MODEL` (e.g., `Qwen/Qwen3-32B`), `SKYAGENT_WEB_CACHE_DIR`, `STEM_LLM_JUDGE_URL`; optional blocklists.

- Dataset:
  ```bash
  python ./data/deep_research.py --output-dir DR_DATA_DIR
  ```

- Web summary (required):
  - Point `WEB_SUMMARY_API_BASE` to your remote OpenAI-compatible endpoint (e.g., `http://host:port/v1`).
  - Keep the model name in `WEB_SUMMARY_MODEL`.
- Optional router (for load-balancing/failover):
  ```bash
  SUMMARY_UPSTREAMS=http://host:port/v1 \
  SUMMARY_MODEL=Qwen/Qwen3-32B \
  PORT=8080 \
  bash services/run_router.sh
  ```
  then set `WEB_SUMMARY_API_BASE=http://<router-host>:8080/v1`.

- Optional: `TRAIN_OUTPUT_DIR`, `ROLLOUT_DIR`, `VAL_ROLLOUT_DIR` for storage paths.

- Run:
  ```bash
  bash ./examples/run_verl/web_research_hle.sh
  ```

### 4) AndroidWorld

Five agent types and two inference backends are supported.

#### Naming Convention

Agent classes follow the `Android{Model}{Input}{Output}Agent` convention:
- **Model**: `Open` (open-source, e.g. UI-TARS) / `API` (proprietary, e.g. GPT)
- **Input**: `Screen` (screenshot) / `Tree` (a11y tree) / `Combo` (both)
- **Output**: Touch (default, omitted) / `ADB` (ADB shell commands)

`AndroidAgent` (the original UI-TARS agent) is a special case and keeps its name.

#### Agent Types

| Agent | Class | Input | Output | Vision |
|-------|-------|-------|--------|--------|
| **Open Screen Touch** (UI-TARS) | `AndroidAgent` | Screenshot | GUI actions | Required (VLM) |
| **API Screen Touch** | `AndroidAPIScreenAgent` | Screenshot | GUI actions (JSON) | Required (VLM) |
| **API Combo Touch** | `AndroidAPIComboAgent` | Screenshot + A11y tree | GUI actions (JSON) | Required (VLM) |
| **API Screen ADB** | `AndroidAPIScreenADBAgent` | Screenshot | ADB shell commands | Required (VLM) |
| **API Tree ADB** | `AndroidAPITreeADBAgent` | A11y tree text | ADB shell commands | Not needed (text LLM) |

#### Inference Backends

| Backend | Engine | Use case |
|---------|--------|----------|
| **VERL** | Local vLLM + Ray (GPU) | Training and inference with local models (e.g. Qwen3-VL-7B) |
| **OpenAI** | Any OpenAI-compatible API | Inference with API models (e.g. GPT-4o, Claude) or remote vLLM |

#### Configuration Matrix

| | VERL (local GPU) | OpenAI API |
|---|---|---|
| **Open Screen Touch** (UI-TARS) | `run_verl/verl_android_inference.yaml` | `run_openai/openai_android_inference.yaml` |
| **API Screen Touch** | — | `run_openai/openai_android_gpt_gui.yaml` |
| **API Combo Touch** | — | `run_openai/openai_android_api_combo.yaml` |
| **API Screen ADB** | `run_verl/verl_android_adb_inference.yaml` | `run_openai/openai_android_adb_inference.yaml` |
| **API Tree ADB** | `run_verl/verl_android_full_adb_inference.yaml` | `run_openai/openai_android_tree_adb_inference.yaml` |

#### Prerequisites

1. **Docker image** -- Build the unified Android container (supports all agent types):

```bash
docker build -f docker/android/Dockerfile.full_adb_agent \
    -t androidworld:full_adb_agent docker/android
```

2. **Data** -- AndroidWorld test instances:

```bash
ls ./data/androidworld_generalization/unseen_task_instance/test.jsonl
```

#### Running with VERL (local model, e.g. Qwen3-VL-7B)

Requires GPUs. Each script handles Ray setup, model loading, container creation, and evaluation.

```bash
# GUI Agent
CUDA_VISIBLE_DEVICES=4,5,6,7 bash ./examples/run_verl/verl_android_inference.sh

# ADB Agent (screenshot + ADB commands)
CUDA_VISIBLE_DEVICES=4,5,6,7 bash ./examples/run_verl/verl_android_adb_inference.sh

# Full ADB Agent (a11y tree text + ADB commands, no vision)
CUDA_VISIBLE_DEVICES=4,5,6,7 bash ./examples/run_verl/verl_android_full_adb_inference.sh
```

Override environment pool size and data file:

```bash
ENV_POOL_SIZE=4 bash ./examples/run_verl/verl_android_full_adb_inference.sh data/test_4_instances.jsonl
```

#### Running with OpenAI API (e.g. GPT-4o)

No GPUs required. Set `OPENAI_API_KEY` and optionally override `MODEL`, `API_URL`, `API_TYPE`.

```bash
# GUI Agent with GPT-4o
OPENAI_API_KEY=sk-... bash ./examples/run_openai/openai_android_inference.sh

# ADB Agent with GPT-4o
OPENAI_API_KEY=sk-... bash ./examples/run_openai/openai_android_inference.sh \
    --yaml examples/run_openai/openai_android_adb_inference.yaml

# Full ADB Agent with GPT-4o (text-only, most cost-effective)
OPENAI_API_KEY=sk-... bash ./examples/run_openai/openai_android_inference.sh \
    --yaml examples/run_openai/openai_android_tree_adb_inference.yaml
```

Or use the Python script directly for more control:

```bash
OPENAI_API_KEY=sk-... python ./examples/run_openai/run_openai_android_inference.py \
    --data ./data/androidworld_generalization/unseen_task_instance/test.jsonl \
    --yaml ./examples/run_openai/openai_android_tree_adb_inference.yaml \
    --model gpt-4o \
    --max-instances 4
```

#### Using a Local vLLM Server via OpenAI Backend

You can serve a local model with vLLM and use the OpenAI backend to call it:

```bash
# Terminal 1: Start vLLM server
vllm serve Qwen/Qwen2-VL-7B-Instruct --port 8000

# Terminal 2: Run inference via OpenAI backend
OPENAI_API_KEY=dummy MODEL=Qwen/Qwen2-VL-7B-Instruct \
    API_URL=http://localhost:8000 API_TYPE=completions \
    bash ./examples/run_openai/openai_android_inference.sh
```

### 5) OSWorld

Placeholder for now. 

### 6) BrowseComp-Plus (Dense Retrieval)

- Prepare dataset/index. First download the decrypted dataset following [official instruction](https://github.com/texttron/BrowseComp-Plus?tab=readme-ov-file#-downloading-the-dataset). Then run:
  ```bash
  python ./data/browsecomp-plus.py --input DECRYPTED_JSON_PATH --output BC_DATA
  ```
- Download Pre-built Index for `Qwen/Qwen3-Embedding-8B`:
  ```bash
  huggingface-cli download Tevatron/browsecomp-plus-indexes --repo-type=dataset --include="qwen3-embedding-8b/*" --local-dir FAISS_INDEX_PATH
  ```

- Serve embedding model:
  - Start an OpenAI-compatible embedding server using `Qwen/Qwen3-Embedding-8B` as the embedding model. For example:
    ```bash
    vllm serve Qwen/Qwen3-Embedding-8B \
    --port 8000 \
    --task embed \
    --max-model-len 8192 \
    --tensor-parallel-size 1 \
    --dtype float16
    ```
  - Configure your `.env` with:
    - `FAISS_EMBEDDING_API_URL` (embedding server base URL)
    - `FAISS_EMBEDDING_MODEL_NAME` (e.g., `Qwen/Qwen3-Embedding-8B` model name used by your server)
    - `FAISS_INDEX_PATH` (file path to the downloaded pre-built index)

- Launch eval (modify the corresponding path in the script first):
  ```bash
  bash ./examples/run_verl/verl_browsecomp.sh
  ```
