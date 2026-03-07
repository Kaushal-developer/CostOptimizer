#!/usr/bin/env bash
# Fine-tune Qwen2.5-7B-Instruct for CostOptimizer
# Prerequisites: pip install peft trl transformers bitsandbytes datasets accelerate
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Step 1: Generate training dataset
echo "=== Step 1: Generating training dataset ==="
python -m src.llm.finetuning.dataset_builder

# Step 2: Run fine-tuning
echo "=== Step 2: Starting QLoRA fine-tuning ==="
python -m src.llm.finetuning.train \
    --dataset data/training_dataset.jsonl \
    --model "Qwen/Qwen2.5-7B-Instruct" \
    --output models/costoptimizer-qwen2.5-7b \
    --epochs 3 \
    --batch-size 4 \
    --lr 2e-4 \
    --lora-rank 16

echo "=== Fine-tuning complete ==="
echo "Model saved to: models/costoptimizer-qwen2.5-7b/"
echo ""
echo "To serve with Ollama:"
echo "  1. Create a Modelfile pointing to the merged model"
echo "  2. ollama create costoptimizer -f Modelfile"
echo "  3. ollama run costoptimizer"
echo ""
echo "To serve with vLLM:"
echo "  vllm serve models/costoptimizer-qwen2.5-7b/merged --port 8001"
