"""Development-only LLM proposals for the deterministic linguistic map."""
from __future__ import annotations

import argparse
import json
import os
import random
import re
from pathlib import Path

from inference.parser_first import (
    _COMMAND_ACTIONS,
    _GH_ACTIONS,
    _GIT_ACTIONS,
    _LINGUISTIC_MAP_PATH,
    _RUNTIME_ACTIONS,
)


def action_catalog() -> dict[str, str]:
    catalog = {f"command:{key}": value for key, value in _COMMAND_ACTIONS.items()}
    catalog.update({f"git:{key}": value for key, value in _GIT_ACTIONS.items()})
    catalog.update({f"gh:{' '.join(key)}": value for key, value in _GH_ACTIONS.items()})
    catalog.update({f"runtime:{key}": value for key, value in _RUNTIME_ACTIONS.items()})
    catalog["command:rg"] = "searching text"
    catalog["command:curl"] = "making an HTTP request"
    return dict(sorted(catalog.items()))


def simulate(seed: int = 20260920) -> list[dict]:
    """Place every atomic phrase in stable single, pair, and triple contexts."""
    rng = random.Random(seed)
    catalog = action_catalog()
    keys = list(catalog)
    rows = []
    for key, phrase in catalog.items():
        others = [candidate for candidate in keys if candidate != key]
        pair_key, third_key = rng.sample(others, 2)
        pair = [phrase, catalog[pair_key]]
        triple = [catalog[third_key], phrase, catalog[pair_key]]
        rows.append({
            "key": key,
            "current_phrase": phrase,
            "simulated_sentences": [
                phrase.capitalize() + ".",
                f"{pair[0].capitalize()} and {pair[1]}.",
                f"{triple[0].capitalize()}, {triple[1]}, and {triple[2]}.",
            ],
        })
    return rows


SYSTEM = """You improve an approved deterministic shell-status phrase map during development.
Each item contains a semantic key, its grounded atomic phrase, and simulated combinations.
Suggest an override only when it improves natural English while preserving exactly the same
meaning. Atomic phrases must start with a present participle, contain no period, command,
flag, invented purpose, or result. Return JSON only: {\"results\":[{\"key\":\"...\",
\"suggested_phrase\":\"...\",\"reason\":\"...\"}]}. Omit keys that should stay unchanged."""


def validate_proposals(raw: list[dict], catalog: dict[str, str] | None = None) -> list[dict]:
    catalog = catalog or action_catalog()
    accepted = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        phrase = item.get("suggested_phrase")
        if key not in catalog or not isinstance(phrase, str):
            continue
        phrase = " ".join(phrase.split()).strip()
        if not phrase or phrase.endswith(".") or any(char in phrase for char in "|;&`\r\n"):
            continue
        if not re.match(r"^[A-Za-z]+ing\b", phrase, re.IGNORECASE):
            continue
        accepted.append({
            "key": key,
            "current_phrase": catalog[key],
            "suggested_phrase": phrase,
            "reason": str(item.get("reason", "")).strip(),
            "accepted": False,
        })
    return accepted


def propose(route: str, model: str, output: Path, seed: int = 20260920) -> dict:
    from labeling.llm import chat, parse_json

    rows = simulate(seed)
    text, usage = chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(rows, ensure_ascii=False)},
    ], model=model)
    parsed = parse_json(text)
    raw = parsed.get("results", []) if isinstance(parsed, dict) else []
    record = {
        "version": 1,
        "route": route,
        "model": model,
        "seed": seed,
        "usage": usage,
        "proposals": validate_proposals(raw),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def apply_reviewed(proposals: Path, destination: Path = _LINGUISTIC_MAP_PATH) -> dict:
    source = json.loads(proposals.read_text(encoding="utf-8"))
    current = json.loads(destination.read_text(encoding="utf-8"))
    overrides = dict(current.get("action_overrides", {}))
    catalog = action_catalog()
    applied = []
    for item in source.get("proposals", []):
        checked = validate_proposals([item], catalog)
        if item.get("accepted") is True and checked:
            proposal = checked[0]
            overrides[proposal["key"]] = proposal["suggested_phrase"]
            applied.append(proposal["key"])
    updated = {"version": 1, "action_overrides": dict(sorted(overrides.items()))}
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return {"applied": applied, "destination": str(destination)}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="linguistic-training")
    sub = parser.add_subparsers(dest="command", required=True)
    simulation = sub.add_parser("simulate")
    simulation.add_argument("--output", type=Path, required=True)
    simulation.add_argument("--seed", type=int, default=20260920)
    proposal = sub.add_parser("propose")
    proposal.add_argument("--route", required=True, help="user-confirmed provider route identity")
    proposal.add_argument("--model", required=True, help="exact user-selected model on that route")
    proposal.add_argument("--output", type=Path, required=True)
    proposal.add_argument("--seed", type=int, default=20260920)
    apply = sub.add_parser("apply")
    apply.add_argument("--input", type=Path, required=True)
    apply.add_argument("--destination", type=Path, default=_LINGUISTIC_MAP_PATH)
    args = parser.parse_args(argv)
    if args.command == "simulate":
        rows = simulate(args.seed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {"simulations": len(rows), "output": str(args.output)}
    elif args.command == "propose":
        result = propose(args.route, args.model, args.output, args.seed)
    else:
        result = apply_reviewed(args.input, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
