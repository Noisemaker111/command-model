"""Deterministic checks for a generated status sentence."""
from __future__ import annotations

import re

from redaction.redact import find_secrets, leaks

MIN_WORDS, MAX_WORDS, HARD_MAX_WORDS = 2, 22, 30
BOILERPLATE = re.compile(r"(?i)^(this|the) (command|script|code|snippet)\b|^(i am|i'm|i will|here is|here's|sure|okay|status:|output:)|\bthis command\b")
SHELL_NOISE = re.compile(r"(\|\s*\w|&&|\|\||\$env:|-ErrorAction|2>&1|>\s*/dev/null|\$\(|`|;\s*\w+\s*-\w)")
PLACEHOLDER = re.compile(r"<(API_KEY|TOKEN|PASSWORD|SECRET|COOKIE|PRIVATE_KEY)>")
ING = re.compile(r"^[A-Z][a-z]+ing\b")


def words(text: str) -> list[str]:
    return re.findall(r"[\w'./\\:<>@+-]+", text)


def check(output: str, command_raw: str | None = None, targets: list[str] | None = None) -> dict:
    out = (output or "").strip()
    w = words(out)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", out) if s.strip()]
    leaked = leaks(out, command_raw) if command_raw else find_secrets(out)
    res = {
        "non_empty": bool(out),
        "one_sentence": bool(out) and "\n" not in out and len(sentences) == 1,
        "ends_with_period": out.endswith("."),
        "length_ok": MIN_WORDS <= len(w) <= MAX_WORDS,
        "length_hard_ok": MIN_WORDS <= len(w) <= HARD_MAX_WORDS,
        "live_tense": bool(ING.match(out)),
        "no_boilerplate": not BOILERPLATE.search(out),
        "no_shell_noise": not SHELL_NOISE.search(out),
        "no_secret": not leaked and not PLACEHOLDER.search(out),
        "words": len(w),
    }
    if targets:
        lower = out.lower()
        hits = sum(1 for t in targets if t and t.lower() in lower)
        res["target_recall"] = round(hits / len(targets), 3)
    res["style_ok"] = all(res[k] for k in ("one_sentence", "length_ok", "live_tense", "no_boilerplate", "no_shell_noise"))
    res["pass"] = res["style_ok"] and res["no_secret"] and res["non_empty"]
    return res


def salient_targets(structure: dict) -> list[str]:
    """Names a status for a simple command should normally mention."""
    acts = structure.get("actions") or []
    meaningful = [a for a in acts if a["type"] not in ("format", "env", "wait")]
    if len(meaningful) != 1:
        return []
    a = meaningful[0]
    if a["type"] in ("read_file", "process_check", "delete", "write_file"):
        return [t for t in a.get("targets", []) if t and not t.startswith("<") and len(t) < 40][:2]
    return []
