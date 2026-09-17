"""SFT (LoRA or full) and optional DPO for the command -> status student.

  python live-status/cli.py train --base HuggingFaceTB/SmolLM2-135M --data v1 --method full --name smol135-full-v1
  python live-status/cli.py train --base <sft-output> --dpo prefs.jsonl --name smol135-dpo-v1

Loss covers only the status tokens (plus EOS). Rows are repeated by their frequency
weight so common command patterns count more. Outputs go to LIVE_STATUS_HOME/models/<name>.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import home, read_jsonl, save_json  # noqa: E402
from labeling.prompts import student_prompt  # noqa: E402

LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def parse(argv):
    p = argparse.ArgumentParser(prog="train")
    p.add_argument("--base", required=True, help="HF model id or local path")
    p.add_argument("--data", default="v1", help="dataset version under LIVE_STATUS_HOME/datasets")
    p.add_argument("--extra", type=Path, action="append", default=[], help="additional train JSONL (command,status)")
    p.add_argument("--name", required=True)
    p.add_argument("--method", choices=["lora", "full"], default="lora")
    p.add_argument("--prompt", choices=["plain", "instruct", "mixed"], default="plain")
    p.add_argument("--epochs", type=float, default=3)
    p.add_argument("--lr", type=float)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--max-len", type=int, default=768)
    p.add_argument("--lora-r", type=int, default=32)
    p.add_argument("--optim", choices=["adamw", "adafactor"], default="adamw",
                   help="adafactor keeps full fine-tunes of 270-360M models inside 8 GB")
    p.add_argument("--no-weights", action="store_true")
    p.add_argument("--dpo", type=Path, help="preference JSONL (command, chosen, rejected) -> DPO stage")
    p.add_argument("--dpo-beta", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=20260916)
    p.add_argument("--cache", type=Path, default=None)
    return p.parse_args(argv)


def load_rows(a) -> tuple[list[dict], list[dict]]:
    d = home() / "datasets" / a.data
    train = list(read_jsonl(d / "train.jsonl"))
    for extra in a.extra:
        train += list(read_jsonl(extra))
    val = list(read_jsonl(d / "validation.jsonl"))
    return train, val


def encode(tok, command: str, status: str, instruct: bool, max_len: int):
    prompt = tok(student_prompt(command, instruct=instruct), add_special_tokens=True).input_ids
    target = tok(" " + status.strip(), add_special_tokens=False).input_ids + [tok.eos_token_id]
    prompt = prompt[-(max_len - len(target)):]
    return prompt + target, [-100] * len(prompt) + target


def batches(items, size, rng, shuffle=True):
    idx = list(range(len(items)))
    if shuffle:
        rng.shuffle(idx)
    # bucket by length inside shuffled chunks for less padding
    chunks = [sorted(idx[i:i + size * 20], key=lambda k: len(items[k][0])) for i in range(0, len(idx), size * 20)]
    out = [c[i:i + size] for c in chunks for i in range(0, len(c), size)]
    if shuffle:
        rng.shuffle(out)
    return out


def collate(torch, items, pad_id, device):
    """Left-padded batch: every target sits at the end, so only the tail needs logits."""
    n = max(len(x[0]) for x in items)
    ids = torch.full((len(items), n), pad_id, dtype=torch.long)
    labels = torch.full((len(items), n), -100, dtype=torch.long)
    attn = torch.zeros((len(items), n), dtype=torch.long)
    for i, (x, y) in enumerate(items):
        ids[i, n - len(x):] = torch.tensor(x); labels[i, n - len(y):] = torch.tensor(y); attn[i, n - len(x):] = 1
    return ids.to(device), labels.to(device), attn.to(device)


def tail_logits(model, ids, labels, attn):
    """Logits for the last K+1 positions (K = longest target) and the matching shifted targets."""
    keep = int((labels != -100).sum(-1).max()) + 1
    pos = (attn.cumsum(-1) - 1).clamp(min=0)
    logits = model(input_ids=ids, attention_mask=attn, position_ids=pos, logits_to_keep=keep).logits
    return logits[:, :-1].float(), labels[:, -(keep - 1):]


def token_loss(torch, model, ids, labels, attn):
    logits, tgt = tail_logits(model, ids, labels, attn)
    return torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), tgt.reshape(-1), ignore_index=-100)


def sequence_logp(torch, model, ids, labels, attn):
    logits, tgt = tail_logits(model, ids, labels, attn)
    lp = torch.log_softmax(logits, -1).gather(-1, tgt.clamp(min=0).unsqueeze(-1)).squeeze(-1)
    return (lp * (tgt != -100)).sum(-1)


def main(argv=None):
    a = parse(argv)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup

    rng = random.Random(a.seed)
    torch.manual_seed(a.seed)
    out = home() / "models" / a.name
    if out.exists():
        raise SystemExit(f"{out} exists; choose a new --name (checkpoints are never overwritten).")
    out.mkdir(parents=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.base, cache_dir=a.cache)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    full = a.method == "full"
    model = AutoModelForCausalLM.from_pretrained(a.base, cache_dir=a.cache,
                                                 dtype=torch.float32 if full else torch.bfloat16).to(device)
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    if not full or a.dpo:
        model.enable_input_require_grads()
        from peft import LoraConfig, get_peft_model
        targets = [t for t in LORA_TARGETS if any(n.endswith(t) for n, _ in model.named_modules())]
        model = get_peft_model(model, LoraConfig(r=a.lora_r, lora_alpha=a.lora_r * 2, lora_dropout=0.05,
                                                 target_modules=targets, task_type="CAUSAL_LM"))
    lr = a.lr or (1e-5 if a.dpo else 5e-5 if full else 2e-4)
    params = [p for p in model.parameters() if p.requires_grad]
    if a.optim == "adafactor":
        from transformers.optimization import Adafactor
        opt = Adafactor(params, lr=lr, scale_parameter=False, relative_step=False, warmup_init=False)
    else:
        opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    log = open(out / "train_log.jsonl", "w", encoding="utf-8")
    t0 = time.time()

    if a.dpo:
        held = set()
        for split in ("test", "validation"):
            f = home() / "datasets" / a.data / f"{split}.jsonl"
            if f.exists():
                held |= {r["id"] for r in read_jsonl(f)}
        prefs = [r for r in read_jsonl(a.dpo) if r.get("id") not in held]
        dropped = sum(1 for r in read_jsonl(a.dpo) if r.get("id") in held)
        print(json.dumps({"pref_pairs": len(prefs), "dropped_held_out": dropped}), flush=True)
        pairs = []
        for r in prefs:
            c = encode(tok, r["command"], r["chosen"], False, a.max_len)
            j = encode(tok, r["command"], r["rejected"], False, a.max_len)
            pairs.append((c, j))
        steps = math.ceil(len(pairs) / a.batch) * max(1, int(a.epochs))
        sched = get_cosine_schedule_with_warmup(opt, max(1, steps // 20), steps)
        step = 0
        model.train()
        for ep in range(max(1, int(a.epochs))):
            order = list(range(len(pairs))); rng.shuffle(order)
            for i in range(0, len(order), a.batch):
                chunk = [pairs[k] for k in order[i:i + a.batch]]
                ids, labels, attn = collate(torch, [c for c, _ in chunk] + [j for _, j in chunk], tok.pad_token_id, device)
                with torch.autocast(device, dtype=torch.bfloat16, enabled=device == "cuda"):
                    pol = sequence_logp(torch, model, ids, labels, attn)
                    with torch.no_grad(), model.disable_adapter():
                        ref = sequence_logp(torch, model, ids, labels, attn)
                n = len(chunk)
                margin = a.dpo_beta * ((pol[:n] - ref[:n]) - (pol[n:] - ref[n:]))
                loss = -torch.nn.functional.logsigmoid(margin).mean()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
                step += 1
                if step % 10 == 0:
                    row = {"step": step, "dpo_loss": round(loss.item(), 4), "acc": round((margin > 0).float().mean().item(), 3)}
                    log.write(json.dumps(row) + "\n"); log.flush(); print(row, flush=True)
        val_loss, best_epoch = None, None
    else:
        train, val = load_rows(a)
        items = []
        for r in train:
            reps = 1 if a.no_weights else max(1, round(r.get("weight", 1)))
            for k in range(reps):
                instruct = a.prompt == "instruct" or (a.prompt == "mixed" and rng.random() < 0.3)
                items.append(encode(tok, r["command"], r["status"], instruct, a.max_len))
        vitems = [encode(tok, r["command"], r["status"], a.prompt == "instruct", a.max_len) for r in val]
        steps = math.ceil(len(items) / a.batch * a.epochs)
        sched = get_cosine_schedule_with_warmup(opt, max(1, steps // 20), steps)
        print(json.dumps({"train_rows": len(train), "train_items": len(items), "val": len(vitems), "steps": steps,
                          "trainable": sum(p.numel() for p in params), "lr": lr}), flush=True)
        step, ep = 0, 0
        best_val, best_epoch, best_state = float("inf"), 0, {}
        while step < steps:
            model.train()
            for b in batches(items, a.batch, rng):
                ids, labels, attn = collate(torch, [items[k] for k in b], tok.pad_token_id, device)
                with torch.autocast(device, dtype=torch.bfloat16, enabled=device == "cuda"):
                    loss = token_loss(torch, model, ids, labels, attn)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
                step += 1
                if step % 25 == 0:
                    row = {"step": step, "epoch": ep, "loss": round(loss.item(), 4), "lr": sched.get_last_lr()[0], "s": round(time.time() - t0)}
                    log.write(json.dumps(row) + "\n"); log.flush()
                if step >= steps:
                    break
            ep += 1
            val_loss = evaluate_loss(torch, model, vitems, tok.pad_token_id, device, a.batch)
            row = {"epoch_end": ep, "step": step, "val_loss": round(val_loss, 4), "s": round(time.time() - t0)}
            log.write(json.dumps(row) + "\n"); log.flush(); print(row, flush=True)
            if val_loss < best_val:
                best_val, best_epoch = val_loss, ep
                best_state = {k: v.detach().to("cpu", copy=True) for k, v in model.state_dict().items()
                              if full or "lora_" in k}
        model.load_state_dict(best_state, strict=False)
        val_loss = best_val

    if hasattr(model, "merge_and_unload"):
        model = model.merge_and_unload()
    model = model.to(torch.bfloat16)
    model.config.use_cache = True
    model.save_pretrained(out, safe_serialization=True)
    tok.save_pretrained(out)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parent).stdout.strip()
    meta = {"name": a.name, "base": a.base, "method": a.method, "prompt": a.prompt, "data": a.data,
            "extra": [str(x) for x in a.extra], "dpo": str(a.dpo) if a.dpo else None, "epochs": a.epochs, "lr": lr,
            "batch": a.batch, "max_len": a.max_len, "optim": a.optim, "seed": a.seed, "git": rev, "seconds": round(time.time() - t0),
            "val_loss": val_loss, "best_epoch": best_epoch, "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
            "peak_mem_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2) if device == "cuda" else None}
    save_json(out / "train_meta.json", meta)
    print(json.dumps(meta), flush=True)


def evaluate_loss(torch, model, items, pad_id, device, size):
    model.eval()
    tot, n = 0.0, 0
    with torch.no_grad():
        for i in range(0, len(items), size):
            ids, labels, attn = collate(torch, items[i:i + size], pad_id, device)
            with torch.autocast(device, dtype=torch.bfloat16, enabled=device == "cuda"):
                loss = token_loss(torch, model, ids, labels, attn)
            k = int((labels != -100).sum())
            tot += loss.item() * k; n += k
    return tot / max(1, n)


if __name__ == "__main__":
    main()
