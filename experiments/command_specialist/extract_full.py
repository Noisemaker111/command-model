"""Recover native Codex command results without executing or replaying any command.

Only top-level completed command events count, never pasted/review transcripts.
Private outputs stay in the ignored work directory. Intent context is not a gold label.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=Path, default=Path.home() / ".codex/sessions")
    parser.add_argument("--before", default="2026-09-07")
    parser.add_argument("--out", type=Path, default=Path("work/command-specialist/full-codex.jsonl.gz"))
    parser.add_argument("--max-output-chars", type=int, default=200_000)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("Output exists; choose a new file to preserve the snapshot.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    counts = collections.Counter()
    sessions = set()
    seen = set()
    with gzip.open(args.out, "wt", encoding="utf-8") as target:
        for file in sorted(args.sessions.rglob("*.jsonl")):
            # Codex rollout names carry the start date. A timestamp check below handles long sessions.
            if file.name.startswith("rollout-") and file.name[8:18] >= args.before:
                continue
            context = ""
            model = None
            with file.open(encoding="utf-8", errors="replace") as source:
                for line_number, line in enumerate(source, 1):
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        counts["malformed_lines"] += 1
                        continue
                    timestamp = str(entry.get("timestamp") or "")
                    if timestamp[:10] >= args.before:
                        continue
                    payload = entry.get("payload") or {}
                    if not isinstance(payload, dict):
                        continue
                    if entry.get("type") == "turn_context":
                        model = payload.get("model")
                    if entry.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
                        context = "\n".join(p.get("text", "") for p in payload.get("content", []) if isinstance(p, dict))[:4000]
                    if entry.get("type") != "event_msg" or payload.get("type") != "item_completed":
                        continue
                    item = payload.get("item") or {}
                    if not isinstance(item, dict) or item.get("type") != "CommandExecution":
                        continue
                    command = item.get("command")
                    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
                        counts["unsupported_command_shape"] += 1
                        continue
                    key = (file.name, item.get("id") or hashlib.sha256(line.encode()).hexdigest())
                    if key in seen:
                        counts["duplicate_events"] += 1
                        continue
                    seen.add(key)
                    output = item.get("aggregated_output") or item.get("formatted_output") or ""
                    if not isinstance(output, str):
                        output = json.dumps(output)
                    local_cap = len(output) > args.max_output_chars
                    source_truncated = "tokens truncated" in output or "<truncated" in output or "bytes omitted" in output
                    row = {"source_file": str(file), "source_line": line_number, "session": file.stem,
                           "timestamp": timestamp, "model": model, "argv": command, "cwd": item.get("cwd"),
                           "exit_code": item.get("exit_code"), "status": item.get("status"),
                           "duration": item.get("duration"), "output": output[:args.max_output_chars],
                           "recorded_output_chars": len(output), "extraction_truncated": local_cap,
                           "source_truncated_detected": source_truncated,
                           "preceding_assistant_context": context, "intent_verified": False}
                    target.write(json.dumps(row, ensure_ascii=False) + "\n")
                    sessions.add(file.name)
                    counts["native_completed_commands"] += 1
                    counts["outputs_over_700_chars"] += len(output) > 700
                    counts["extraction_truncated"] += local_cap
                    counts["source_truncated_detected"] += source_truncated
                    counts["explicit_exit_zero"] += item.get("exit_code") == 0
    report = {"counts": dict(counts), "sessions": len(sessions), "before": args.before,
              "scope": "native Codex completed-command events only; older response-only formats are not recovered here",
              "intent_is_verified": False,
              "artifact_sha256": hashlib.sha256(args.out.read_bytes()).hexdigest()}
    Path(str(args.out) + ".summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
