"""Export a trained checkpoint to GGUF and register quantized Ollama models.

  python live-status/cli.py export_gguf --name smol135-full-v1 --quants f16 q8_0 q6_K q5_K_M q4_K_M

Conversion uses llama.cpp's convert_hf_to_gguf.py (LLAMA_CPP_DIR); quantization below
q8_0 is done by `ollama create --quantize`. Ollama models are named
live-status-<name>-<quant>.
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
    a = p.parse_args(argv)
    src = home() / "models" / a.name
    out = src / "gguf"
    out.mkdir(exist_ok=True)
    converter = a.llama_cpp / "convert_hf_to_gguf.py"
    results = {}
    base_types = {"f16": "f16", "q8_0": "q8_0"}
    for outtype in {base_types[q] for q in a.quants if q in base_types} | {"f16"}:
        target = out / f"{a.name}-{outtype}.gguf"
        if not target.exists():
            subprocess.run([sys.executable, str(converter), str(src), "--outfile", str(target), "--outtype", outtype], check=True)
        results[outtype] = {"gguf": str(target), "bytes": target.stat().st_size}
    for q in a.quants:
        tag = f"live-status-{a.name}-{q}".lower()
        gguf = out / f"{a.name}-{'q8_0' if q == 'q8_0' else 'f16'}.gguf"
        mf = out / f"Modelfile-{q}"
        mf.write_text(MODELFILE.format(path=gguf.as_posix()), encoding="utf-8")
        cmd = ["ollama", "create", tag, "-f", str(mf)]
        if q not in ("f16", "q8_0"):
            cmd[2:2] = ["--quantize", q]
        subprocess.run(cmd, check=True, capture_output=True)
        show = subprocess.run(["ollama", "show", tag], capture_output=True, text=True).stdout
        results.setdefault(q, {})["ollama"] = tag
        results[q]["show"] = " ".join(show.split())[:200]
    (out / "export.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
