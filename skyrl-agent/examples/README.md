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

#### Prerequisites

1. **Docker image** — build the unified container (see [`docker/android/README.md`](../../docker/android/README.md)):
   ```bash
   docker build -f docker/android/Dockerfile.full_adb_agent \
       -t androidworld:full_adb_agent docker/android
   ```

2. **Install** — from the `skyrl-agent/` directory:
   ```bash
   uv sync --extra verl   # for verl backend
   uv sync                # for openai backend only
   ```

3. **Test data** — already in the repo:
   ```bash
   ls ./data/androidworld_generalization/unseen_task_instance/test_seed7.jsonl
   ```

#### Agent Types

| Agent | Input | Output | VLM needed? | Best for |
|---|---|---|---|---|
| `AndroidAgent` | Screenshot | UI-TARS JSON | Yes | UI-TARS checkpoint |
| `AndroidAPIScreenAgent` | Screenshot | JSON actions | Yes | GPT/Qwen VLMs |
| `AndroidAPIScreenADBAgent` | Screenshot | ADB commands | Yes | GPT/Qwen VLMs |
| `AndroidAPITreeADBAgent` | A11y tree | ADB commands | No | Any text LLM |
| `AndroidAPIComboAgent` | Screenshot + tree | ADB commands | Yes | GPT/Qwen VLMs |
| `AndroidM3AAgent` | Screenshot + SOM | Index JSON | Yes | SOM-based evaluation |
| `AndroidT3AAgent` | A11y tree | Index JSON | No | Text-only baseline |
| `AndroidT3AADBAgent` | A11y tree | ADB commands | No | Text-only + ADB |
| `AndroidMobileUseAgent` | Screenshot | MobileUse pipeline | Yes | Multi-agent hierarchy |

Text-only agents (`*Tree*`, `T3A*`) work with any LLM — no vision model required.

#### Backends

| Backend | When to use | GPU needed? |
|---|---|---|
| **OpenAI** (`run_openai/`) | Inference with any OpenAI-compatible API (OpenAI, local vLLM, etc.) | No |
| **VERL** (`run_verl/`) | Training or inference with local model weights via FSDP + vLLM | Yes |

#### Quick Start: OpenAI Backend

```bash
# Screenshot agent with GPT
OPENAI_API_KEY=sk-... ./examples/run_openai/openai_android_inference.sh

# M3A agent (SOM-based)
OPENAI_API_KEY=sk-... ./examples/run_openai/openai_android_m3a_inference.sh

# T3A-ADB agent (text-only, cheapest)
OPENAI_API_KEY=sk-... ./examples/run_openai/openai_android_t3a_adb_inference.sh

# MobileUse agent (multi-agent hierarchy)
OPENAI_API_KEY=sk-... ./examples/run_openai/openai_android_mobileuse_inference.sh
```

With a local vLLM server instead of OpenAI:

```bash
OPENAI_API_KEY=dummy API_URL=http://localhost:8000 \
  MODEL=Qwen/Qwen2-VL-7B-Instruct API_TYPE=completions \
  ./examples/run_openai/openai_android_inference.sh
```

#### Quick Start: VERL Backend

Requires GPUs. Handles Ray setup, model loading, containers, and evaluation.

```bash
# Inference only
CUDA_VISIBLE_DEVICES=4,5 ./examples/run_verl/verl_android_inference.sh

# T3A-ADB agent (text-only)
CUDA_VISIBLE_DEVICES=4,5 ./examples/run_verl/verl_android_t3a_adb_inference.sh

# Training
CUDA_VISIBLE_DEVICES=0,1,2,3 ./examples/run_verl/verl_android.sh
```

#### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | (required) | API key (use `dummy` for local vLLM) |
| `MODEL` | `gpt-5-mini` | Model name |
| `API_URL` | `https://api.openai.com` | API endpoint |
| `API_TYPE` | `chat` | `chat` or `completions` |
| `ENV_POOL_SIZE` | `16` | Number of Android containers |
| `CUDA_VISIBLE_DEVICES` | all | GPUs to use (verl backend) |
| `DEBUG` | `0` | Set to `1` for single-container debug mode |

#### Container Modes

Scripts create containers automatically (**Mode A**) unless `broker_url` is set in the YAML config (**Mode B**). See [`docker/android/README.md`](../../docker/android/README.md) for details.

### 5) BrowseComp-Plus (Dense Retrieval)

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
