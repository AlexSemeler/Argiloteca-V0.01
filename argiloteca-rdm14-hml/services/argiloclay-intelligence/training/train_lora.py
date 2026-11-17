"""Optional local CUDA LoRA recipe. No cloud job or publication. Not run on the VM."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(); p.add_argument("--reviewed-data", type=Path, required=True)
    p.add_argument("--base-model", default="Qwen/Qwen3-1.7B"); p.add_argument("--output", default="storage/lora-candidate")
    args = p.parse_args()
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer, AutoModelForCausalLM, Trainer, TrainingArguments, DataCollatorForSeq2Seq
    if not torch.cuda.is_available():
        raise SystemExit("Esta receita exige GPU CUDA local. Na VM CPU use apenas inferência quantizada.")
    for split in ("train", "validation"):
        if not (args.reviewed_data / (split + ".jsonl")).is_file():
            raise SystemExit("Faltam splits revisados.")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    use_bf16 = torch.cuda.is_bf16_supported()
    model = AutoModelForCausalLM.from_pretrained(args.base_model, torch_dtype=torch.bfloat16 if use_bf16 else torch.float16)
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, bias="none",
                target_modules=["q_proj", "k_proj", "v_proj", "o_proj"], task_type="CAUSAL_LM"))
    model.config.use_cache = False; model.enable_input_require_grads()

    def tokenize(row):
        messages = row["messages"]
        prefix = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True, enable_thinking=False)
        full = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False, enable_thinking=False)
        if full[:len(prefix)] != prefix or len(full) > 2048 or len(full) <= len(prefix):
            raise ValueError("Template incompatível ou exemplo excede 2048 tokens; revise o dado.")
        return {"input_ids": full, "attention_mask": [1] * len(full), "labels": [-100] * len(prefix) + full[len(prefix):]}

    data = load_dataset("json", data_files={s: str(args.reviewed_data / (s + ".jsonl")) for s in ("train", "validation")})
    data = data.map(tokenize, remove_columns=data["train"].column_names)
    config = TrainingArguments(output_dir=args.output, num_train_epochs=2, learning_rate=1e-4,
        per_device_train_batch_size=1, per_device_eval_batch_size=1, gradient_accumulation_steps=8,
        gradient_checkpointing=True, bf16=use_bf16, fp16=not use_bf16, eval_strategy="epoch", save_strategy="epoch",
        logging_steps=10, save_total_limit=2, seed=42, report_to=[], optim="adamw_torch")
    trainer = Trainer(model=model, args=config, train_dataset=data["train"], eval_dataset=data["validation"],
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100))
    trainer.train(); trainer.save_model(args.output); tokenizer.save_pretrained(args.output)
    Path(args.output, "candidate.json").write_text(json.dumps({"base_model": args.base_model, "production_approved": False}))


if __name__ == "__main__":
    main()
