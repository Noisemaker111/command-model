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

from common import ROOT, _main_checkout, home, read_jsonl, save_json, write_jsonl  # noqa: E402
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
    """requests: [{"id", "state", "questions"}] -> {id: result}. Secret-bearing states are never sent."""
    load_env()
    withheld = {r["id"]: {"id": r["id"], "error": "withheld: secret-like state"}
                for r in requests if find_secrets(json.dumps(r["state"], ensure_ascii=False))}
    requests = [r for r in requests if r["id"] not in withheld]
    if not requests:
        return withheld
    if os.environ.get("TYPESAFE_API_KEY"):
        with ThreadPoolExecutor(concurrency) as pool:
            return {**withheld, **{x["id"]: x for x in pool.map(_direct, requests)}}
    if not os.environ.get("AI_GATEWAY_API_KEY"):
        raise RuntimeError("set TYPESAFE_API_KEY or AI_GATEWAY_API_KEY (command-model/.env)")
    proc = subprocess.run(["bun", str(BRIDGE)], input="\n".join(json.dumps(r) for r in requests), text=True,
                          capture_output=True, encoding="utf-8", env={**os.environ, "JEV_CONCURRENCY": str(concurrency)})
    if proc.returncode:
        raise RuntimeError(proc.stderr[-500:])
    return {**withheld, **{x["id"]: x for x in map(json.loads, proc.stdout.splitlines()) if x}}


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
        if cid not in cmds:
            continue
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
    rows = [{"key": k, "opus_pass": truth[k], **graded[k], "combined": combined(graded[k])} for k in ok]
    write_jsonl(home() / "evaluation" / "jev_calibration_pairs.jsonl", rows)
    rep = {"pairs": len(pairs), "graded": len(ok), "errors": len(pairs) - len(ok),
           "opus_pass_rate": round(sum(truth[k] for k in ok) / max(1, len(ok)), 3),
           "auc": {f: round(auc([r[f] for r in rows], [r["opus_pass"] for r in rows]), 3) for f in FEATURES},
           "rule": fit_rule(rows),
           "first_error": next((graded[k]["error"] for k in graded if "error" in graded[k]), None)}
    save_json(home() / "evaluation" / "jev_calibration.json", rep)
    return rep


REF_QUESTIONS = {
    "same_actions": {"type": "boolean", "instructions": "The output status describes the same actions as the reference status (wording may differ; it may omit only trivial details)."},
    "invented": {"type": "boolean", "instructions": "The output status mentions an action, target, file or outcome that is in neither the command nor the reference."},
    "quality": {"type": "score", "instructions": "How well does the output status match the reference status as a description of the command?",
                "criteria": ["wrong or misleading", "partly right, missing key actions", "right but vague",
                             "right and specific", "as good as the reference"]},
}


def grade_against_reference(items: list[tuple[str, str, str, str]]) -> dict[str, dict]:
    """items: (key, command, reference, output) -> {key: {"same", "invented", "quality", "score"}}"""
    res = evaluate([{"id": k, "state": {"command": c, "reference": ref, "output": out}, "questions": REF_QUESTIONS}
                    for k, c, ref, out in items])
    graded = {}
    for k, r in res.items():
        if "error" in r:
            graded[k] = {"error": r["error"]}
            continue
        a = r["answers"]
        g = {"same": a["same_actions"]["probability"], "invented": a["invented"]["probability"], "quality": a["quality"]["score"]}
        g["score"] = g["same"] * (1 - g["invented"]) * (g["quality"] / 4)
        graded[k] = g
    return graded


def calibrate_eval(limit: int) -> dict:
    """Agreement with Opus 5 evaluation verdicts on saved benchmark outputs (reference-based grading)."""
    from evaluation.evaluate import ACCEPT_SCORE, load_cache
    cache = load_cache()
    items, truth, seen = [], {}, set()
    for f in sorted((home() / "evaluation" / "outputs").glob("*.jsonl")):
        for o in read_jsonl(f):
            v = cache.get(o.get("jkey"))
            key = o.get("jkey")
            if not v or key in seen or not o["output"] or find_secrets(json.dumps(o["command"])):
                continue
            seen.add(key)
            items.append((key, o["command"], o["status"], o["output"]))
            truth[key] = bool(v.get("correct")) and v.get("score", 0) >= ACCEPT_SCORE
            if limit and len(items) >= limit:
                break
    graded = grade_against_reference(items)
    rows = [{"key": k, "opus_pass": truth[k], **graded[k]} for k in truth if "error" not in graded.get(k, {"error": 1})]
    write_jsonl(home() / "evaluation" / "jev_eval_calibration_pairs.jsonl", rows)
    labels = [r["opus_pass"] for r in rows]
    best = max(({"threshold": t / 100, "accuracy": round(sum((r["score"] >= t / 100) == r["opus_pass"] for r in rows) / len(rows), 3)}
                for t in range(1, 100)), key=lambda x: x["accuracy"])
    rep = {"pairs": len(items), "graded": len(rows), "opus_pass_rate": round(sum(labels) / max(1, len(rows)), 3),
           "auc": {f: round(auc([r[f] if f != "invented" else -r[f] for r in rows], labels), 3) for f in ("same", "invented", "quality", "score")},
           "best_threshold": best}
    save_json(home() / "evaluation" / "jev_eval_calibration.json", rep)
    return rep


FEATURES = ("accurate", "complete", "names", "quality", "combined")
RULE_PATH = "jev_rule.json"


def combined(g: dict) -> float:
    return g["accurate"] * g["complete"] * (g["quality"] / 4)


def auc(scores: list[float], labels: list[bool]) -> float:
    """Probability a random Opus-pass pair outscores a random Opus-fail pair (ties count half)."""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    pos = sum(labels)
    neg = len(labels) - pos
    if not pos or not neg:
        return float("nan")
    return (sum(r for r, l in zip(ranks, labels) if l) - pos * (pos + 1) / 2) / (pos * neg)


def fit_rule(rows: list[dict]) -> dict:
    """Best single threshold on `combined`, plus thresholds with >= 0.9 precision for each direction."""
    best = None
    for t in [x / 100 for x in range(1, 100)]:
        tp = sum(1 for r in rows if r["combined"] >= t and r["opus_pass"])
        fp = sum(1 for r in rows if r["combined"] >= t and not r["opus_pass"])
        tn = sum(1 for r in rows if r["combined"] < t and not r["opus_pass"])
        acc = (tp + tn) / len(rows)
        prec = tp / max(1, tp + fp)
        # confident-fail threshold: below it, Opus almost never passes the pair
        below = [r for r in rows if r["combined"] < t]
        fail_prec = sum(1 for r in below if not r["opus_pass"]) / max(1, len(below))
        cand = {"threshold": t, "accuracy": round(acc, 3), "pass_precision": round(prec, 3),
                "pass_coverage": round((tp + fp) / len(rows), 3), "fail_precision": round(fail_prec, 3),
                "fail_coverage": round(len(below) / len(rows), 3)}
        if best is None or acc > best["accuracy"]:
            best = cand
        if fail_prec >= 0.9 and ("confident_fail" not in best or t > best["confident_fail"]["threshold"]):
            best["confident_fail"] = cand
    save_json(home() / "evaluation" / RULE_PATH, best)
    return best


def choose(items: list[tuple[str, str, dict[str, str]]]) -> dict[str, dict]:
    """Pick the best candidate per command. Choice returns one of the option keys, so the
    winning *text* comes back too: Jev emits text only by selecting an input.

    items: (key, command, {candidate_key: sentence}) -> {key: {"choice", "text", "probabilities", "confidence"}}
    """
    reqs = []
    for k, cmd, cands in items:
        if len(cands) < 2:
            continue
        reqs.append({"id": k, "state": {"command": cmd, "candidates": cands},
                     "questions": {"best": {"type": "choice",
                                            "instructions": "Which candidate is the best live status sentence for this command: accurate, complete, specific about names, and concise?",
                                            "criteria": {ck: text for ck, text in cands.items()}}}})
    res = evaluate(reqs)
    out = {}
    for k, cmd, cands in items:
        r = res.get(k)
        if not r or "error" in r:
            out[k] = {"error": (r or {}).get("error", "missing"), "choice": None,
                      "text": next(iter(cands.values())) if len(cands) == 1 else None}
            continue
        a = r["answers"]["best"]
        out[k] = {"choice": a["choice"], "text": cands.get(a["choice"]),
                  "probabilities": a.get("probabilities"), "confidence": (r.get("confidence") or {}).get("best")}
    return out


def calibrate_choice(limit: int) -> dict:
    """How often Jev's Choice picks the same candidate Opus's judge picked."""
    cmds = {r["id"]: r for r in read_jsonl(home() / "commands_redacted.jsonl")}
    from judging.judge import latest_judgements
    items, truth, scores = [], {}, {}
    for cid, j in latest_judgements().items():
        cands = {k: v for k, v in j["candidates"].items() if isinstance(v, str)}
        if cid not in cmds or len(cands) < 2 or not j.get("best") or j["best"] not in cands:
            continue
        items.append((cid, cmds[cid]["command_redacted"], cands))
        truth[cid] = j["best"]
        scores[cid] = {k: (j["verdicts"].get(k) or {}).get("score") for k in cands}
        if limit and len(items) >= limit:
            break
    picked = choose(items)
    ok = [k for k in truth if picked.get(k, {}).get("choice")]
    agree = sum(1 for k in ok if picked[k]["choice"] == truth[k])
    # "no worse" = Jev's pick scored at least as high as Opus's pick under Opus's own scores
    no_worse = sum(1 for k in ok if (scores[k].get(picked[k]["choice"]) or 0) >= (scores[k].get(truth[k]) or 0))
    conf = [picked[k]["confidence"] for k in ok if picked[k].get("confidence") is not None]
    hi = [k for k in ok if (picked[k].get("confidence") or 0) >= 0.5]
    rep = {"items": len(items), "chosen": len(ok), "agreement": round(agree / max(1, len(ok)), 3),
           "no_worse_by_opus_score": round(no_worse / max(1, len(ok)), 3),
           "mean_confidence": round(sum(conf) / max(1, len(conf)), 3) if conf else None,
           "high_confidence_share": round(len(hi) / max(1, len(ok)), 3),
           "agreement_when_confident": round(sum(1 for k in hi if picked[k]["choice"] == truth[k]) / max(1, len(hi)), 3)}
    save_json(home() / "evaluation" / "jev_choice_calibration.json", rep)
    return rep


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["calibrate", "calibrate-eval", "calibrate-choice"])
    p.add_argument("--limit", type=int, default=400)
    a = p.parse_args()
    fn = {"calibrate": calibrate, "calibrate-eval": calibrate_eval, "calibrate-choice": calibrate_choice}[a.action]
    print(json.dumps(fn(a.limit), indent=2))
