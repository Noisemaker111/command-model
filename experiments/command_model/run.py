"""Read-only inspection handoff: intent in, readable plan and faithful evidence out.

This callable/CLI is a pilot integration boundary, not an installed host plugin.
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from benchmark import PredictionError, predict
from bindings import bind_request
from contract import evidence_result, execute_plan


def inspect_request(root: Path, request: str, *, targets: dict[str, str] | None = None,
                    evidence_request: str | None = None,
                    model="shell-specialist-pilot", base_url="http://127.0.0.1:11434",
                    backend="powershell", artifacts=Path("work/command-specialist/runs"),
                    num_ctx=4096, num_predict=160, evidence_max_lines=100,
                    evidence_max_chars=8000, packet_max_chars=2000):
    if not isinstance(request, str) or not request.strip():
        raise ValueError("request must be a nonempty string")
    if evidence_request is not None and not isinstance(evidence_request, str):
        raise ValueError("evidence_request must be a string")
    settings = dict(num_ctx=num_ctx, num_predict=num_predict,
                    evidence_max_lines=evidence_max_lines, evidence_max_chars=evidence_max_chars,
                    packet_max_chars=packet_max_chars)
    if any(type(value) is not int or value < 1 for value in settings.values()):
        raise ValueError("runtime limits must be positive integers")
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("root must name a directory")
    start = time.perf_counter()
    bound = bind_request(root, request, targets) if targets is not None else None
    case = bound.case() if bound else {"kind": "plan", "request": request}
    try:
        prediction, planning = predict(base_url, model, case, num_ctx=num_ctx, num_predict=num_predict)
    except PredictionError as error:
        artifacts = Path(artifacts)
        artifacts.mkdir(parents=True, exist_ok=True)
        artifact = artifacts / (uuid.uuid4().hex + ".json")
        artifact.write_text(json.dumps({"request": bound.display_request if bound else request,
                            "model": model, "runtime": settings, "planning": error.timing,
                            "planning_error": str(error), "executed": False}, indent=2,
                            ensure_ascii=False), encoding="utf-8")
        raise ValueError(f"{error}; no command executed; raw result: {artifact.resolve()}") from error
    plan = bound.resolve(prediction) if bound else prediction
    # Revalidate the resolved path immediately before execution in either backend.
    execution_start = time.perf_counter()
    result = execute_plan(plan, root, backend=backend)
    execution_ms = (time.perf_counter() - execution_start) * 1000
    artifacts = Path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    artifact = artifacts / (uuid.uuid4().hex + ".json")
    display_request = bound.display_request if bound else request
    saved = {"request": display_request, "plan": plan, "result": result,
             "model": model, "planning": planning, "runtime": settings, "execution_ms": execution_ms}
    if bound:
        saved["binding_trace"] = {"template": request, "targets": dict(targets),
                                  "model_request": bound.model_request,
                                  "references": dict(bound.paths), "prediction": prediction}
    # Save before optional selection: rejected selections never lose raw output.
    artifact.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    packet = {"request": display_request, "plan": plan, "backend": backend,
              "exit_code": result["exit_code"], "raw_result": str(artifact.resolve()),
              "stderr": result["stderr"][:packet_max_chars], "stderr_truncated": len(result["stderr"]) > packet_max_chars}
    if evidence_request:
        lines = result["stdout"].splitlines()
        chosen = lines[:evidence_max_lines]
        selected_case = {"kind": "evidence", "request": evidence_request,
                         "output_lines": chosen, "exit_code": result["exit_code"],
                         "truncated": len(lines) > len(chosen)}
        packet["evidence_window"] = {"total_lines": len(lines), "included_lines": len(chosen),
                                     "max_chars": evidence_max_chars}
        saved["evidence_request"] = evidence_request
        if not chosen:
            # Exact empty output has no selectable evidence; inference adds no information.
            saved["selection"] = {"lines": []}
            saved["selection_method"] = "empty_output"
            packet.update(evidence_result(saved["selection"], selected_case))
        elif len("\n".join(chosen)) > evidence_max_chars:
            packet.update({"selection_error": "Output window exceeds evidence_max_chars; inspect the raw result.",
                           "truncated": True})
        else:
            try:
                selection, selection_timing = predict(base_url, model, selected_case,
                                                      num_ctx=num_ctx, num_predict=num_predict)
                saved["selection"] = selection
                saved["selection_timing"] = selection_timing
                packet.update(evidence_result(selection, selected_case))
            except (ValueError, TypeError, OSError, TimeoutError) as error:
                if hasattr(error, "timing"):
                    saved["selection_timing"] = error.timing
                packet.update({"selection_error": str(error), "truncated": True})
    else:
        packet.update({"stdout": result["stdout"][:packet_max_chars], "truncated": len(result["stdout"]) > packet_max_chars})
    packet["runtime"] = settings
    packet["fallback"] = "inspect_raw_result" if packet.get("selection_error") or packet.get("truncated") or packet["stderr_truncated"] else None
    saved["packet"] = dict(packet)
    # Preserve the pre-selection raw artifact even if this final audit write fails.
    final_artifact = artifact.with_suffix(".tmp")
    final_artifact.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    final_artifact.replace(artifact)
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
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--num-predict", type=int, default=160)
    parser.add_argument("--evidence-max-lines", type=int, default=100)
    parser.add_argument("--evidence-max-chars", type=int, default=8000)
    parser.add_argument("--packet-max-chars", type=int, default=2000)
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
                             model=args.model, base_url=args.base_url, backend=args.backend, artifacts=args.artifacts,
                             num_ctx=args.num_ctx, num_predict=args.num_predict,
                             evidence_max_lines=args.evidence_max_lines, evidence_max_chars=args.evidence_max_chars,
                             packet_max_chars=args.packet_max_chars)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(packet, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
