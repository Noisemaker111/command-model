"""Model backends: Ollama (GGUF via llama.cpp), llama-server, and Transformers (checkpoints).

All backends take a *redacted* command and return (status, metrics).
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

from labeling.prompts import EXAMPLES, STUDENT_INSTRUCTION, fit_command, structured_student_input, student_prompt

MAX_NEW_TOKENS = 48


def clean(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^(status|output|answer)\s*:\s*", "", t, flags=re.I)
    t = t.splitlines()[0].strip() if t else ""
    t = t.strip("\"'` *")
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    if m:
        t = m.group(1)
    if t and t[-1] not in ".!?":
        t += "."
    return t[:1].upper() + t[1:]


def _few_shot_messages(command: str, *, structured: bool = False) -> list[dict]:
    msgs = [{"role": "system", "content": STUDENT_INSTRUCTION}]
    for block in EXAMPLES.split("\n\n")[:4]:
        cmd, status = block.split("\nStatus: ")
        example = cmd.removeprefix("Command: ")
        msgs.append({"role": "user", "content": structured_student_input(example) if structured else example})
        msgs.append({"role": "assistant", "content": status})
    content = structured_student_input(command) if structured else fit_command(command)
    msgs.append({"role": "user", "content": content})
    return msgs


def _post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class OllamaBackend:
    """Plain is fine-tuned completion format; long prepends the instruction.
    Structured-plain completes over the deterministic parse; instruct uses few-shot chat."""

    def __init__(self, model: str, url: str = "http://127.0.0.1:11434", mode: str = "plain",
                 timeout: float = 20.0, keep_alive: str = "30m", cpu: bool = False, threads: int | None = None):
        self.model, self.url, self.mode, self.timeout, self.keep_alive = model, url.rstrip("/"), mode, timeout, keep_alive
        self.cpu, self.threads = cpu, threads
        self.name = f"ollama:{model}:{mode}" + (":cpu" if cpu else "")

    def _options(self, temperature: float | None = None, seed: int | None = None) -> dict:
        opts = {"temperature": 0 if temperature is None else temperature,
                "num_predict": MAX_NEW_TOKENS, "stop": ["\n"], "num_ctx": 2048}
        if seed is not None:
            opts["seed"] = seed
        if self.cpu:
            opts["num_gpu"] = 0
        if self.threads:
            opts["num_thread"] = self.threads
        return opts

    def generate(self, command: str, temperature: float | None = None, seed: int | None = None) -> tuple[str, dict]:
        opts = self._options(temperature, seed)
        t0 = time.perf_counter()
        if self.mode in ("plain", "long", "structured-plain"):
            out = _post(f"{self.url}/api/generate", {"model": self.model,
                                                    "prompt": student_prompt(command, instruct=self.mode == "long",
                                                                             structured=self.mode == "structured-plain"),
                                                    "raw": True, "stream": False, "options": opts, "keep_alive": self.keep_alive}, self.timeout)
            text = out.get("response", "")
        else:
            out = _post(f"{self.url}/api/chat", {"model": self.model, "messages": _few_shot_messages(command, structured=self.mode == "structured"), "stream": False,
                                                "think": False, "options": opts, "keep_alive": self.keep_alive}, self.timeout)
            text = (out.get("message") or {}).get("content", "")
        wall = time.perf_counter() - t0
        ev, evd = out.get("eval_count") or 0, (out.get("eval_duration") or 0) / 1e9
        return clean(text), {"wall_s": wall, "output_tokens": ev, "prompt_tokens": out.get("prompt_eval_count"),
                             "tokens_per_s": (ev / evd) if evd else None, "load_s": (out.get("load_duration") or 0) / 1e9,
                             "raw": text}

    def warm(self) -> None:
        _post(f"{self.url}/api/generate", {"model": self.model, "prompt": "", "keep_alive": self.keep_alive,
                                           "stream": False, "options": self._options()}, 120)


class LlamaServerBackend:
    """llama.cpp `llama-server` /completion endpoint (plain format)."""

    def __init__(self, url: str = "http://127.0.0.1:8080", timeout: float = 20.0):
        self.url, self.timeout, self.name = url.rstrip("/"), timeout, f"llama-server:{url}"

    def generate(self, command: str) -> tuple[str, dict]:
        t0 = time.perf_counter()
        out = _post(f"{self.url}/completion", {"prompt": student_prompt(command, instruct=False), "n_predict": MAX_NEW_TOKENS,
                                              "temperature": 0, "stop": ["\n"], "cache_prompt": True}, self.timeout)
        timings = out.get("timings") or {}
        return clean(out.get("content", "")), {"wall_s": time.perf_counter() - t0, "output_tokens": timings.get("predicted_n"),
                                               "tokens_per_s": timings.get("predicted_per_second"), "raw": out.get("content")}


class HFBackend:
    """Transformers checkpoint (optionally with a LoRA adapter) for pre-export evaluation."""

    def __init__(self, base: str, adapter: str | None = None, instruct: bool = False,
                 structured: bool = False, device: str = "cuda", max_len: int = 1024):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(adapter or base)
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        model = AutoModelForCausalLM.from_pretrained(base, dtype=dtype).to(device)
        if adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter).merge_and_unload()
        self.model = model.eval()
        self.device, self.instruct, self.structured, self.max_len = device, instruct, structured, max_len
        self.name = f"hf:{adapter or base}"

    def generate(self, command: str) -> tuple[str, dict]:
        torch = self.torch
        ids = self.tok(student_prompt(command, instruct=self.instruct, structured=self.structured), return_tensors="pt").input_ids
        if ids.shape[1] > self.max_len:
            head = int(self.max_len * 0.7)
            ids = self.torch.cat((ids[:, :head], ids[:, -(self.max_len - head):]), dim=1)
        ids = ids.to(self.device)
        t0 = time.perf_counter()
        with torch.no_grad():
            out = self.model.generate(ids, attention_mask=torch.ones_like(ids), max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
                                      eos_token_id=self._stop_ids(), pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id)
        new = out[0, ids.shape[1]:]
        wall = time.perf_counter() - t0
        text = self.tok.decode(new, skip_special_tokens=True)
        return clean(text), {"wall_s": wall, "output_tokens": int(new.shape[0]), "prompt_tokens": int(ids.shape[1]),
                             "tokens_per_s": new.shape[0] / wall if wall else None, "raw": text}

    def _stop_ids(self) -> list[int]:
        ids = {self.tok.eos_token_id}
        nl = self.tok.encode("\n", add_special_tokens=False)
        if len(nl) == 1:
            ids.add(nl[0])
        return [i for i in ids if i is not None]


def from_spec(spec: str):
    """ollama:<model>[:mode][:cpu] | llama-server:<url> | hf:<base>[@<adapter>][:structured]"""
    kind, _, rest = spec.partition(":")
    if kind == "ollama":
        mode, cpu = "plain", False
        if rest.endswith(":cpu"):
            rest, cpu = rest[:-4], True
        for m in ("structured-plain", "plain", "instruct", "long", "structured"):
            if rest.endswith(":" + m):
                rest, mode = rest[: -len(m) - 1], m
        return OllamaBackend(rest, mode=mode, cpu=cpu)
    if kind == "llama-server":
        return LlamaServerBackend(rest or "http://127.0.0.1:8080")
    if kind == "hf":
        structured = rest.endswith(":structured")
        if structured:
            rest = rest[:-len(":structured")]
        base, _, adapter = rest.partition("@")
        return HFBackend(base, adapter or None, structured=structured)
    raise ValueError(f"unknown backend spec {spec}")
