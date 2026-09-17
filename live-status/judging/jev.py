"""TypeSafe Jev as a fast, cheap status grader (choices, scores, probabilities; never text).

Transport: direct TypeSafe API when TYPESAFE_API_KEY is set, otherwise Vercel AI Gateway
through the Bun bridge in jev/evaluate.ts (evaluation is AI SDK-only on the gateway).
Keys are read from the environment or the main checkout's .env; only redacted text is sent.

  python live-status/judging/jev.py calibrate --limit 400   # agreement with Opus 5 verdicts
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import ROOT, _main_checkout, home, read_jsonl, save_json  # noqa: E402
from redaction.redact import find_secrets  # noqa: E402

BRIDGE = ROOT / "jev" / "evaluate.ts"

# Gateway question types use "boolean"; the direct API calls the same thing "noul".
QUESTIONS = {
    "accurate": {"type": "boolean", "instructions": "The status sentence only describes actions that are visible in the command; it invents no actions, targets, outcomes or intent."},
    "complete": {"type": "boolean", "instructions": "The status sentence mentions every meaningful action in the command (trivial plumbing like cd, formatting or echo separators may be omitted)."},
    "names": {"type": "boolean", "instructions": "The status sentence keeps the important file, project, process, package or service names from the command."},
    "quality": {"type": "score", "instructions": "How good is the status sentence as a live UI status for this command?",
                "criteria": ["unusable: wrong or misleading", "poor: vague or missing key actions",
                             "acceptable: correct but imperfect", "good: correct and specific", "excellent: ship unchanged"]},
}


def load_env() -> None:
    env = _main_checkout() / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def _direct(req: dict) -> dict:
    qs = {k: ({**q, "type": "noul"} if q["type"] == "boolean" else q) for k, q in req["questions"].items()}
    body = json.dumps({"state": req["state"], "model": "jev-latest", "questions": qs}).encode()
    http = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(http, timeout=30) as r:
            out = json.loads(r.read())
    except Exception as exc:
        return {"id": req["id"], "error": str(exc)[:300]}
    answers = {}
    for k, a in out.get("answers", {}).items():
        answers[k] = {"type": "boolean", "probability": a["noul"]} if a.get("type") == "noul" else a
    return {"id": req["id"], "answers": answers, "usage": out.get("usage")}


def evaluate(requests: list[dict], concurrency: int = 16) -> dict[str, dict]:
    """requests: [{"id", "state", "questions"}] -> {id: result}. Refuses secret-bearing state."""
    load_env()
    for r in requests:
        if find_secrets(json.dumps(r["state"], ensure_ascii=False)):
            raise ValueError(f"refusing to send secret-like state for {r['id']}")
    if os.environ.get("TYPESAFE_API_KEY"):
        with ThreadPoolExecutor(concurrency) as pool:
            return {x["id"]: x for x in pool.map(_direct, requests)}
    if not os.environ.get("AI_GATEWAY_API_KEY"):
        raise RuntimeError("set TYPESAFE_API_KEY or AI_GATEWAY_API_KEY (command-model/.env)")
    proc = subprocess.run(["bun", str(BRIDGE)], input="\n".join(json.dumps(r) for r in requests), text=True,
                          capture_output=True, encoding="utf-8", env={**os.environ, "JEV_CONCURRENCY": str(concurrency)})
    if proc.returncode:
        raise RuntimeError(proc.stderr[-500:])
    return {x["id"]: x for x in map(json.loads, proc.stdout.splitlines()) if x}


def grade(pairs: list[tuple[str, str, str]]) -> dict[str, dict]:
    """pairs: (key, command, status) -> {key: {"accurate", "complete", "names", "quality", "pass"} or {"error"}}"""
    res = evaluate([{"id": k, "state": {"command": c, "status": s}, "questions": QUESTIONS} for k, c, s in pairs])
    out = {}
    for k, r in res.items():
        if "error" in r:
            out[k] = {"error": r["error"]}
            continue
        a = r["answers"]
        g = {q: a[q]["probability"] for q in ("accurate", "complete", "names")}
        g["quality"] = a["quality"]["score"]  # 0..4
        g["pass"] = g["accurate"] >= 0.5 and g["quality"] >= 2.5
        out[k] = g
    return out


def calibrate(limit: int) -> dict:
    """Agreement between Jev and Opus 5 per-candidate verdicts on already-judged commands."""
    cmds = {r["id"]: r for r in read_jsonl(home() / "commands_redacted.jsonl")}
    from judging.judge import latest_judgements
    pairs, truth = [], {}
    for cid, j in list(latest_judgements().items()):
        for ck, text in j["candidates"].items():
            v = j["verdicts"].get(ck)
            if not isinstance(v, dict) or "score" not in v:
                continue
            key = f"{cid}|{ck}"
            pairs.append((key, cmds[cid]["command_redacted"], text))
            truth[key] = bool(v.get("correct")) and v["score"] >= 85
        if limit and len(pairs) >= limit:
            break
    graded = grade(pairs)
    ok = [k for k in truth if "error" not in graded.get(k, {"error": 1})]
    tp = sum(1 for k in ok if graded[k]["pass"] and truth[k])
    fp = sum(1 for k in ok if graded[k]["pass"] and not truth[k])
    fn = sum(1 for k in ok if not graded[k]["pass"] and truth[k])
    tn = len(ok) - tp - fp - fn
    rep = {"pairs": len(pairs), "graded": len(ok), "errors": len(pairs) - len(ok),
           "agreement": round((tp + tn) / max(1, len(ok)), 3), "precision": round(tp / max(1, tp + fp), 3),
           "recall": round(tp / max(1, tp + fn), 3), "opus_pass_rate": round(sum(truth[k] for k in ok) / max(1, len(ok)), 3),
           "first_error": next((graded[k]["error"] for k in graded if "error" in graded[k]), None)}
    save_json(home() / "evaluation" / "jev_calibration.json", rep)
    return rep


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["calibrate"])
    p.add_argument("--limit", type=int, default=400)
    print(json.dumps(calibrate(p.parse_args().limit), indent=2))
