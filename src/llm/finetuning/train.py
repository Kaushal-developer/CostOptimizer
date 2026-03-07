"""
Fine-tune Qwen2.5-7B-Instruct for cloud cost optimization using QLoRA.

Requirements:
    pip install peft trl transformers bitsandbytes datasets accelerate

Usage:
    python -m src.llm.finetuning.train --dataset data/training_dataset.jsonl
    # Or use the shell script:
    bash scripts/finetune.sh
"""

from __future__ import annotations

import argparse
from pathlib import Path


def train(
    dataset_path: str,
    model_name: str = "Qwen/Qwen2.5-7B-Instruct",
    output_dir: str = "models/costoptimizer-qwen2.5-7b",
    epochs: int = 3,
    batch_size: int = 4,
    learning_rate: float = 2e-4,
    lora_rank: int = 16,
    lora_alpha: int = 32,
    max_seq_length: int = 2048,
    use_4bit: bool = True,
) -> None:
    """Run QLoRA fine-tuning."""
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model, TaskType
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from trl import SFTTrainer, SFTConfig

    print(f"Loading dataset from {dataset_path}...")
    dataset = load_dataset("json", data_files=dataset_path, split="train")
    print(f"Dataset: {len(dataset)} examples")

    # Quantization config for 4-bit training
    bnb_config = None
    if use_4bit:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

    print(f"Loading model: {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    model.config.use_cache = False

    # LoRA configuration
    lora_config = LoraConfig(
        r=lora_rank,
        lora_alpha=lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )

    model = get_peft_model(model, lora_config)
    trainable, total = model.get_nb_trainable_parameters()
    print(f"Trainable parameters: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)")

    # Format messages for training
    def format_messages(example):
        messages = example["messages"]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        return {"text": text}

    dataset = dataset.map(format_messages, remove_columns=dataset.column_names)

    # Training config
    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        gradient_checkpointing=True,
        learning_rate=learning_rate,
        weight_decay=0.01,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
        max_seq_length=max_seq_length,
        dataset_text_field="text",
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        args=training_args,
        processing_class=tokenizer,
    )

    print("Starting training...")
    trainer.train()

    # Save the LoRA adapter
    adapter_path = Path(output_dir) / "adapter"
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    print(f"LoRA adapter saved to {adapter_path}")

    # Optionally merge and save full model
    merged_path = Path(output_dir) / "merged"
    print(f"Merging adapter into base model at {merged_path}...")
    merged_model = model.merge_and_unload()
    merged_model.save_pretrained(str(merged_path))
    tokenizer.save_pretrained(str(merged_path))
    print(f"Merged model saved to {merged_path}")
    print("Training complete!")


def main():
    parser = argparse.ArgumentParser(description="Fine-tune Qwen2.5-7B for cloud cost optimization")
    parser.add_argument("--dataset", required=True, help="Path to training JSONL")
    parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct", help="Base model")
    parser.add_argument("--output", default="models/costoptimizer-qwen2.5-7b", help="Output dir")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--no-4bit", action="store_true", help="Disable 4-bit quantization")
    args = parser.parse_args()

    train(
        dataset_path=args.dataset,
        model_name=args.model,
        output_dir=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        lora_rank=args.lora_rank,
        max_seq_length=args.max_seq_length,
        use_4bit=not args.no_4bit,
    )


if __name__ == "__main__":
    main()
