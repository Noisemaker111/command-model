"""Measure token reduction with an explicitly named tokenizer, not chars/4."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("work/command-specialist"))
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    cases = {c["id"]: c for c in map(json.loads, (args.data / "test.jsonl").read_text(encoding="utf-8").splitlines())}
    results = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines()]
    total_raw = total_compact = count = 0
    for result in results:
        if result["kind"] != "evidence" or not result.get("passed"):
            continue
        case = cases[result["id"]]
        raw = json.dumps({"exit_code": case["exit_code"], "truncated": case["truncated"], "output": "\n".join(case["output_lines"])})
        compact = json.dumps(result["result"])
        total_raw += len(tokenizer.encode(raw, add_special_tokens=False))
        total_compact += len(tokenizer.encode(compact, add_special_tokens=False))
        count += 1
    report = {"tokenizer": "Qwen/Qwen2.5-Coder-1.5B-Instruct", "successful_evidence_cases": count,
              "raw_tokens": total_raw, "compact_tokens": total_compact,
              "token_reduction": 1 - total_compact / total_raw if total_raw else None,
              "warning": "This tokenizer is not the frontier provider's tokenizer; only successful cases counted."}
    args.results.with_name(args.results.stem + "-tokens.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
