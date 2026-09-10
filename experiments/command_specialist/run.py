"""Try the local specialist against an explicitly chosen directory.

Five read-only operations only. No host plugin or permission bypass is installed.
"""
import argparse
import json
import time
import uuid
from pathlib import Path

from benchmark import predict
from contract import evidence_result, execute_plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--evidence-request")
    parser.add_argument("--model", default="shell-specialist-pilot")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--backend", choices=["powershell", "native"], default="powershell")
    parser.add_argument("--artifacts", type=Path, default=Path("work/command-specialist/runs"))
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir():
        raise SystemExit("--root must name a directory")
    start = time.perf_counter()
    plan, planning = predict(args.base_url, args.model, {"kind": "plan", "request": args.request})
    result = execute_plan(plan, root, backend=args.backend)
    args.artifacts.mkdir(parents=True, exist_ok=True)
    artifact = args.artifacts / (uuid.uuid4().hex + ".json")
    # Save before optional selection so rejected selections never lose the raw result.
    artifact.write_text(json.dumps({"request": args.request, "plan": plan, "result": result}, indent=2), encoding="utf-8")
    packet = {"plan": plan, "backend": args.backend, "exit_code": result["exit_code"], "raw_result": str(artifact.resolve()),
              "stderr": result["stderr"][:2000], "stderr_truncated": len(result["stderr"]) > 2000}
    if args.evidence_request:
        lines = result["stdout"].splitlines()
        # Explicit bounded window for this pilot; full output remains in the artifact.
        chosen = lines[:100]
        selected_case = {"kind": "evidence", "request": args.evidence_request,
                         "output_lines": chosen, "exit_code": result["exit_code"],
                         "truncated": len(lines) > len(chosen)}
        if sum(len(line) for line in chosen) > 8000:
            packet.update({"selection_error": "Output window exceeds pilot context budget; inspect the raw result.",
                           "truncated": True})
        else:
            try:
                selection, _ = predict(args.base_url, args.model, selected_case)
                packet.update(evidence_result(selection, selected_case))
            except (ValueError, TypeError) as error:
                packet.update({"selection_error": str(error), "truncated": True})
    else:
        packet.update({"stdout": result["stdout"][:2000], "truncated": len(result["stdout"]) > 2000})
    packet["planning_ms"] = planning["inference_wall_ms"]
    packet["wall_ms"] = (time.perf_counter() - start) * 1000
    print(json.dumps(packet, indent=2))


if __name__ == "__main__":
    main()
