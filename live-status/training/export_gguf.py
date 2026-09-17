"""Export a trained checkpoint to GGUF and register each quantization as an Ollama model.

  python live-status/cli.py export_gguf --name v1-qwen3-06b-lora --quants f16 q8_0 q6_K q5_K_M q4_K_M

f16 and q8_0 come straight from llama.cpp's convert_hf_to_gguf.py (LLAMA_CPP_DIR); k-quants
are made from the f16 file with llama-quantize (LLAMA_QUANTIZE; the prebuilt llama.cpp
release works). Current Ollama cannot quantize GGUF imports, so every level is imported
as a finished GGUF. Ollama models are named live-status-<name>-<quant> (lowercase).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import home  # noqa: E402

DEFAULT_LLAMA = Path.home() / "Projects/command-model/.worktrees/command-specialist/work/llama.cpp"
DEFAULT_QUANTIZE = home() / "tools" / "llama-b11020-cpu" / "llama-quantize.exe"

MODELFILE = """FROM {path}
TEMPLATE \"\"\"{{{{ .Prompt }}}}\"\"\"
PARAMETER temperature 0
PARAMETER num_ctx 2048
PARAMETER num_predict 48
"""


def main(argv=None):
    p = argparse.ArgumentParser(prog="export_gguf")
    p.add_argument("--name", required=True)
    p.add_argument("--quants", nargs="+", default=["f16", "q8_0", "q4_K_M"])
    p.add_argument("--llama-cpp", type=Path, default=Path(os.environ.get("LLAMA_CPP_DIR", DEFAULT_LLAMA)))
    p.add_argument("--quantize-bin", type=Path, default=Path(os.environ.get("LLAMA_QUANTIZE", DEFAULT_QUANTIZE)))
    a = p.parse_args(argv)
    src = home() / "models" / a.name
    out = src / "gguf"
    out.mkdir(exist_ok=True)
    converter = a.llama_cpp / "convert_hf_to_gguf.py"
    results = {}
    for q in ["f16", *[x for x in a.quants if x != "f16"]]:
        target = out / f"{a.name}-{q}.gguf"
        if not target.exists():
            if q in ("f16", "q8_0"):
                cmd = [sys.executable, str(converter), str(src), "--outfile", str(target), "--outtype", q]
            else:
                cmd = [str(a.quantize_bin), str(out / f"{a.name}-f16.gguf"), str(target), q.upper()]
            subprocess.run(cmd, check=True, capture_output=True)
        results[q] = {"gguf": str(target), "bytes": target.stat().st_size}
        if q not in a.quants:
            continue
        tag = f"live-status-{a.name}-{q}".lower()
        mf = out / f"Modelfile-{q}"
        mf.write_text(MODELFILE.format(path=target.as_posix()), encoding="utf-8")
        done = subprocess.run(["ollama", "create", tag, "-f", str(mf)], capture_output=True, text=True, encoding="utf-8")
        if done.returncode:
            raise SystemExit(f"ollama create {tag} failed: {done.stderr.strip()[-300:]}")
        results[q]["ollama"] = tag
    (out / "export.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
