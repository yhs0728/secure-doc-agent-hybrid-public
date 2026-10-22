#!/bin/sh
# Foreground, separate CPU-only Ollama for compose.validation.cpu.yaml.
set -eu
model_dir="${VALIDATION_OLLAMA_MODELS:-/usr/share/ollama/.ollama/models}"
if [ ! -d "$model_dir" ]; then
  echo 'Set VALIDATION_OLLAMA_MODELS to an existing Ollama model directory.' >&2
  exit 1
fi
command -v ollama >/dev/null
export OLLAMA_HOST="${VALIDATION_OLLAMA_HOST:-172.17.0.1:11435}"
export OLLAMA_MODELS="$model_dir"
export CUDA_VISIBLE_DEVICES=-1
export ROCR_VISIBLE_DEVICES=-1
export GGML_VK_VISIBLE_DEVICES=-1
export OLLAMA_VULKAN=0
export OLLAMA_INTEL_GPU=false
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_CONTEXT_LENGTH=2048
export OLLAMA_NOPRUNE=1
export OLLAMA_NO_CLOUD=1
exec ollama serve
