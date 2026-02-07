#!/bin/bash
# Patch vLLM 0.11.0 to fix cu_seqlens CUDA device bug in qwen2_vl.py
# Run this after `uv sync` if using vLLM 0.11.0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/../.venv"
QWEN2_VL_FILE="${VENV_DIR}/lib/python3.12/site-packages/vllm/model_executor/models/qwen2_vl.py"

if [ ! -f "$QWEN2_VL_FILE" ]; then
    echo "Error: qwen2_vl.py not found at $QWEN2_VL_FILE"
    exit 1
fi

# Check if patch already applied
if grep -q "cu_seqlens.to(device=self.device)" "$QWEN2_VL_FILE"; then
    echo "Patch already applied to qwen2_vl.py"
    exit 0
fi

# Apply patch: add .to(device) after F.pad line
sed -i '/cu_seqlens = F.pad(cu_seqlens, (1, 0), "constant", 0)/a\        cu_seqlens = cu_seqlens.to(device=self.device)  # Fix: move to CUDA for flash_attn' "$QWEN2_VL_FILE"

if [ $? -eq 0 ]; then
    echo "Successfully patched qwen2_vl.py"
else
    echo "Error: Failed to patch qwen2_vl.py"
    exit 1
fi
