"""Turn judged labels into train/validation/test/rejected/manual_review splits.

Leakage control: commands are clustered into families (identical template, or
MinHash-estimated Jaccard >= 0.7 on character shingles) and whole families are
assigned to one split. The test split is then topped up with hard families.
Test/validation assignments persist across rebuilds (datasets/frozen_families.json).
"""
from __future__ import annotations

import collections
import hashlib
import math
import random
import re

from common import home, read_jsonl, save_json, write_jsonl
from data_miner.mine import _bucket, template_key
from judging.judge import latest_judgements

ACCEPT, REVIEW = 85, 70
HARD = ("long_powershell", "nested_quoting", "loop", "conditional", "pipeline", "chained", "natural_language",
        "injection_like", "secret", "malformed", "uncommon_tool", "inline_script", "heredoc", "very_long")
ADVERSARIAL_TAGS = ("secret", "injection_like", "synthetic")
PERM = 64
BANDS = 16


def decide(j: dict) -> tuple[str, str]:
    v = j["validators"]
    score = j.get("recommended_score")
    if not isinstance(score, (int, float)):
        scores = [c.get("score", 0) for c in j["verdicts"].values() if isinstance(c, dict)]
        score = max(scores) if scores else 0
    best = j["verdicts"].get(j.get("best") or "", {}) if isinstance(j.get("verdicts"), dict) else {}
    if not v["no_secret"] or best.get("secret_leak"):
        return "rejected", "secret"
    if score >= ACCEPT and v["pass"] and not j["uncertain"]:
        return "accepted", "ok"
    if score >= REVIEW or (score >= ACCEPT and (j["uncertain"] or not v["pass"])):
        return "manual_review", "uncertain" if j["uncertain"] else "validators" if not v["pass"] else "score"
    return "rejected", "low_score"


def _shingles(text: str, k: int = 5) -> set[str]:
    t = re.sub(r"\s+", " ", text.lower())
    return {t[i:i + k] for i in range(max(1, len(t) - k + 1))}


def _minhash(sh: set[str]) -> list[int]:
    hs = [int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little") for s in sh]
    return [min(((h ^ (seed * 0x9E3779B97F4A7C15)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF for h in hs) for seed in range(1, PERM + 1)]


def families(rows: list[dict]) -> dict[str, str]:
    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    sigs = {}
    by_band = collections.defaultdict(list)
    per = PERM // BANDS
    for r in rows:
        sig = _minhash(_shingles(template_key(r["command"])))
        sigs[r["id"]] = sig
        for b in range(BANDS):
            by_band[(b, tuple(sig[b * per:(b + 1) * per]))].append(r["id"])
    for ids in by_band.values():
        if len(ids) < 2:
            continue
        head = ids[0]
        for other in ids[1:]:
            if find(head) == find(other):
                continue
            same = sum(x == y for x, y in zip(sigs[head], sigs[other])) / PERM
            if same >= 0.7:
                union(head, other)
    return {i: find(i) for i in parent}


def _split_of(family: str, seed: int) -> str:
    x = int(hashlib.sha256(f"{seed}:{family}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if x < 0.1 else "validation" if x < 0.2 else "train"


def build(seed: int = 20260916, version: str = "v1", freeze: bool = True) -> dict:
    cmds = {r["id"]: r for r in read_jsonl(home() / "commands_redacted.jsonl")}
    judged = latest_judgements()
    buckets = collections.defaultdict(list)
    for cid, j in judged.items():
        r = cmds.get(cid)
        if not r:
            continue
        verdict, reason = decide(j)
        row = {"id": cid, "command": r["command_redacted"], "status": j["recommended_output"], "shell": r["shell"],
               "score": j.get("recommended_score"), "reason": reason, "uncertain": j["uncertain"],
               "candidates": j["candidates"], "best": j.get("best"), "notes": j.get("notes"),
               "tags": r["tags"], "complexity": r["complexity"], "length": r["length"], "count": r["count"],
               "sources": r["sources"], "action_types": r["structure"]["action_types"],
               "weight": round(min(4.0, 1 + math.log2(r["count"])), 2), "existing_model_text": r.get("existing_model_text")}
        buckets[verdict].append(row)

    accepted = buckets["accepted"]
    fam = families(accepted)
    frozen_path = home() / "datasets" / "frozen_families.json"
    frozen = {}
    if frozen_path.exists():
        import json
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    for r in accepted:
        r["family"] = fam[r["id"]]
    # a family inherits a frozen split if any member was frozen there before
    fam_split = {}
    for r in accepted:
        f = r["family"]
        prior = frozen.get(r["id"])
        if prior in ("test", "validation"):
            fam_split[f] = prior
        fam_split.setdefault(f, None)
    for f in fam_split:
        if fam_split[f] is None:
            fam_split[f] = _split_of(f, seed)

    # top up hard examples in test by moving whole (small) train families
    rng = random.Random(seed)
    fam_members = collections.defaultdict(list)
    for r in accepted:
        fam_members[r["family"]].append(r)
    for tag in HARD + ("synthetic",):
        tagged = [r for r in accepted if tag in r["tags"]]
        # adversarial categories get a larger share of test: they are rare and safety-critical
        want = (len(tagged) // 2 if tag in ADVERSARIAL_TAGS else min(15, max(1, len(tagged) // 8))) if tagged else 0
        have = sum(1 for r in tagged if fam_split[r["family"]] == "test")
        cands = sorted({r["family"] for r in tagged if fam_split[r["family"]] == "train" and r["id"] not in frozen},
                       key=lambda f: (len(fam_members[f]), rng.random()))
        for f in cands:
            if have >= want:
                break
            if len(fam_members[f]) > 5:
                continue
            fam_split[f] = "test"
            have += sum(1 for r in fam_members[f] if tag in r["tags"])

    splits = collections.defaultdict(list)
    for r in accepted:
        splits[fam_split[r["family"]]].append(r)
    out_dir = home() / "datasets" / version
    counts = {}
    for name in ("train", "validation", "test"):
        rows = sorted(splits[name], key=lambda r: r["id"])
        counts[name] = write_jsonl(out_dir / f"{name}.jsonl", rows)
    counts["rejected"] = write_jsonl(out_dir / "rejected.jsonl", buckets["rejected"])
    counts["manual_review"] = write_jsonl(out_dir / "manual_review.jsonl", buckets["manual_review"])
    new_frozen = dict(frozen)
    for name in ("test", "validation"):
        for r in splits[name]:
            new_frozen.setdefault(r["id"], name)
    if freeze:
        save_json(frozen_path, new_frozen)

    leak = _leak_check(splits)
    report = {"version": version, "seed": seed, "counts": counts, "families": len(set(fam.values())),
              "cross_split_template_collisions": leak, "distributions": {n: distribution(splits[n]) for n in ("train", "validation", "test")},
              "rejected_reasons": dict(collections.Counter(r["reason"] for r in buckets["rejected"])),
              "review_reasons": dict(collections.Counter(r["reason"] for r in buckets["manual_review"]))}
    save_json(out_dir / "report.json", report)
    return {k: report[k] for k in ("version", "counts", "families", "cross_split_template_collisions", "rejected_reasons", "review_reasons")}


def _leak_check(splits) -> int:
    train = {template_key(r["command"]) for r in splits["train"]}
    return sum(1 for n in ("validation", "test") for r in splits[n] if template_key(r["command"]) in train)


def distribution(rows: list[dict]) -> dict:
    C = collections.Counter
    d = {"n": len(rows), "shell": C(), "length": C(), "complexity": C(), "action": C(), "source": C(), "frequency": C(), "tags": C()}
    for r in rows:
        d["shell"][r["shell"]] += 1
        d["length"][_bucket(r["length"])] += 1
        d["complexity"][r["complexity"]] += 1
        for a in r["action_types"]:
            d["action"][a] += 1
        for s in r["sources"]:
            d["source"][s] += 1
        d["frequency"]["1" if r["count"] == 1 else "2-4" if r["count"] < 5 else "5+"] += 1
        for t in r["tags"]:
            d["tags"][t] += 1
    return {k: (dict(v.most_common()) if isinstance(v, collections.Counter) else v) for k, v in d.items()}
