"""Read-only inspection handoff: intent in, readable plan and faithful evidence out.

This callable/CLI is a pilot integration boundary, not an installed host plugin.
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from benchmark import predict
from bindings import bind_request
from contract import evidence_result, execute_plan


def inspect_request(root: Path, request: str, *, targets: dict[str, str] | None = None,
                    evidence_request: str | None = None,
                    model="shell-specialist-pilot", base_url="http://127.0.0.1:11434",
                    backend="powershell", artifacts=Path("work/command-specialist/runs")):
    if not isinstance(request, str) or not request.strip():
        raise ValueError("request must be a nonempty string")
    if evidence_request is not None and not isinstance(evidence_request, str):
        raise ValueError("evidence_request must be a string")
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("root must name a directory")
    start = time.perf_counter()
    bound = bind_request(root, request, targets) if targets is not None else None
    case = bound.case() if bound else {"kind": "plan", "request": request}
    prediction, planning = predict(base_url, model, case)
    plan = bound.resolve(prediction) if bound else prediction
    # Revalidate the resolved path immediately before execution in either backend.
    result = execute_plan(plan, root, backend=backend)
    artifacts = Path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    artifact = artifacts / (uuid.uuid4().hex + ".json")
    display_request = bound.display_request if bound else request
    saved = {"request": display_request, "plan": plan, "result": result,
             "model": model, "planning": planning}
    if bound:
        saved["binding_trace"] = {"template": request, "targets": dict(targets),
                                  "model_request": bound.model_request,
                                  "references": dict(bound.paths), "prediction": prediction}
    # Save before optional selection: rejected selections never lose raw output.
    artifact.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    packet = {"request": display_request, "plan": plan, "backend": backend,
              "exit_code": result["exit_code"], "raw_result": str(artifact.resolve()),
              "stderr": result["stderr"][:2000], "stderr_truncated": len(result["stderr"]) > 2000}
    if evidence_request:
        lines = result["stdout"].splitlines()
        chosen = lines[:100]
        selected_case = {"kind": "evidence", "request": evidence_request,
                         "output_lines": chosen, "exit_code": result["exit_code"],
                         "truncated": len(lines) > len(chosen)}
        if sum(len(line) for line in chosen) > 8000:
            packet.update({"selection_error": "Output window exceeds pilot context budget; inspect the raw result.",
                           "truncated": True})
        else:
            try:
                selection, _ = predict(base_url, model, selected_case)
                packet.update(evidence_result(selection, selected_case))
            except (ValueError, TypeError) as error:
                packet.update({"selection_error": str(error), "truncated": True})
    else:
        packet.update({"stdout": result["stdout"][:2000], "truncated": len(result["stdout"]) > 2000})
    packet["planning_ms"] = planning["inference_wall_ms"]
    packet["wall_ms"] = (time.perf_counter() - start) * 1000
    return packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    task = parser.add_mutually_exclusive_group(required=True)
    task.add_argument("--request")
    task.add_argument("--task-file", type=Path, help="JSON with request, targets and optional evidence_request")
    parser.add_argument("--target", action="append", default=[], metavar="NAME=RELATIVE_PATH")
    parser.add_argument("--evidence-request")
    parser.add_argument("--model", default="shell-specialist-pilot")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--backend", choices=["powershell", "native"], default="powershell")
    parser.add_argument("--artifacts", type=Path, default=Path("work/command-specialist/runs"))
    args = parser.parse_args()
    if args.task_file:
        if args.target or args.evidence_request:
            parser.error("--task-file supplies targets and evidence_request")
        payload = json.loads(args.task_file.read_text(encoding="utf-8-sig"))
        if (not isinstance(payload, dict) or not {"request", "targets"} <= payload.keys()
                or payload.keys() - {"request", "targets", "evidence_request"}):
            parser.error("task file requires request and targets, with optional evidence_request")
        request, targets = payload["request"], payload["targets"]
        if not isinstance(targets, dict):
            parser.error("task targets must be an object")
        evidence_request = payload.get("evidence_request")
    else:
        request, targets, evidence_request = args.request, None, args.evidence_request
        if args.target:
            targets = {}
            for value in args.target:
                name, separator, path = value.partition("=")
                if not separator or name in targets:
                    parser.error("targets must be distinct NAME=RELATIVE_PATH bindings")
                targets[name] = path
    packet = inspect_request(args.root, request, targets=targets, evidence_request=evidence_request,
                             model=args.model, base_url=args.base_url, backend=args.backend, artifacts=args.artifacts)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(packet, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
