"""Local response-only LoRA SFT. Stores adapter weights, never publishes them."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("work/command-specialist"))
    parser.add_argument("--model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("work/hf-cache"))
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from huggingface_hub import snapshot_download
    from peft import LoraConfig, get_peft_model

    cache = snapshot_download(args.model, cache_dir=args.cache,
                              allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"])
    if args.download_only:
        print(json.dumps({"snapshot": str(cache)}), flush=True)
        return
    if not torch.cuda.is_available():
        raise SystemExit("A working CUDA environment is required for this measured training pilot.")
    output = args.output or args.data / "adapter"
    if output.exists():
        raise SystemExit("Adapter output already exists; use a new directory.")
    output.mkdir(parents=True)
    seed = 20260909
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(6)
    tokenizer = AutoTokenizer.from_pretrained(cache, local_files_only=True)
    tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(cache, torch_dtype=torch.bfloat16,
                                                device_map={"": 0}, attn_implementation="sdpa", local_files_only=True)
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                                           target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
                                           bias="none", task_type="CAUSAL_LM"))
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model.train()
    rows = [json.loads(line) for line in (args.data / "sft.jsonl").read_text(encoding="utf-8").splitlines()]
    encoded = []
    for row in rows:
        prompt = tokenizer.apply_chat_template(row["messages"][:-1], tokenize=True, add_generation_prompt=True)
        full = tokenizer.apply_chat_template(row["messages"], tokenize=True, add_generation_prompt=False)
        if full[:len(prompt)] != prompt:
            raise RuntimeError("Chat-template prompt is not a prefix; response loss mask would be wrong.")
        if len(full) > 2048:
            raise RuntimeError(f"Example {row['id']} exceeds context; do not silently truncate labels.")
        labels = [-100] * len(prompt) + full[len(prompt):]
        encoded.append((full, labels))
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)
    accumulation = 4
    total_steps = math.ceil(len(encoded) / accumulation) * args.epochs
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    start = time.perf_counter()
    step = 0
    print(json.dumps({"phase": "training", "examples": len(encoded), "optimizer_steps": total_steps,
                      "trainable_parameters": trainable, "max_sequence": max(len(x[0]) for x in encoded)}), flush=True)
    with (output / "training.jsonl").open("w", encoding="utf-8") as log:
        for epoch in range(args.epochs):
            order = list(range(len(encoded)))
            random.shuffle(order)
            for offset in range(0, len(order), accumulation):
                batch = order[offset:offset + accumulation]
                optimizer.zero_grad(set_to_none=True)
                loss_sum = 0.0
                for i in batch:
                    tokens, labels = encoded[i]
                    inputs = torch.tensor([tokens], device="cuda")
                    targets = torch.tensor([labels], device="cuda")
                    loss = model(input_ids=inputs, attention_mask=torch.ones_like(inputs), labels=targets).loss
                    if not torch.isfinite(loss):
                        raise RuntimeError("Non-finite training loss")
                    (loss / len(batch)).backward()
                    loss_sum += loss.detach().float().item()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                step += 1
                warmup = max(1, int(total_steps * .05))
                scale = min(1, step / warmup) * max(.1, (total_steps - step) / max(1, total_steps - warmup))
                for group in optimizer.param_groups:
                    group["lr"] = 2e-4 * scale
                optimizer.step()
                row = {"step": step, "epoch": epoch + 1, "loss": loss_sum / len(batch),
                       "elapsed_seconds": time.perf_counter() - start}
                log.write(json.dumps(row) + "\n")
                log.flush()
                if step % 10 == 0 or step == 1:
                    print(json.dumps(row), flush=True)
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    # Preserve the canonical base model ID, so downstream converters find its config.
    model.peft_config["default"].base_model_name_or_path = args.model
    model.save_pretrained(output)
    tokenizer.save_pretrained(output)
    report = {"model": args.model, "base_snapshot": Path(cache).name, "epochs": args.epochs,
              "examples": len(encoded), "trainable_parameters": trainable, "optimizer_steps": step,
              "training_seconds": elapsed, "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
              "gpu": torch.cuda.get_device_name(0), "torch": torch.__version__, "transformers": transformers.__version__,
              "seed": seed, "precision": "bfloat16 LoRA, no base quantization", "max_context": 2048,
              "sft_sha256": hashlib.sha256((args.data / "sft.jsonl").read_bytes()).hexdigest(),
              "test_used_for_training": False}
    (output / "training-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
