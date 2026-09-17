"""Inventory, extraction, deduplication and statistics for historical commands.

Outputs (under LIVE_STATUS_HOME):
  inventory.json                        sources, file counts, sizes, unparsed locations
  private/records.jsonl                 every extracted execution (raw + redacted)
  private/commands.jsonl                deduplicated command groups with raw representative
  commands_redacted.jsonl               the same groups without raw text (teacher/judge input)
  reports/mining_stats.{json,md}        distributions
"""
from __future__ import annotations

import collections
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import home, private_dir, read_jsonl, save_json, sha, write_jsonl  # noqa: E402
from data_miner.sources import HOME, REGISTRY, UNPARSED  # noqa: E402
from parsers.shell import ACTIONS, analyze, complexity  # noqa: E402
from redaction.redact import redact  # noqa: E402

MAX_COMMAND_CHARS = 6000

UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
HEX = re.compile(r"\b[0-9a-f]{7,64}\b", re.I)
ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
NUM = re.compile(r"\d+")
TEMP = re.compile(r"(?i)(\\temp\\|/tmp/)[^\s\\/\"']+")
INJECTION = re.compile(r"(?i)(ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the|all)|you are now|system prompt|new instructions|return only|print your (instructions|prompt)|act as|jailbreak|do not summari[sz]e)")
NATURAL = re.compile(r"[\"']([A-Za-z][a-z]+(?:[ ,]+[A-Za-z']+){6,}[.!?]?)")


def inventory() -> dict:
    rows = []
    for src in REGISTRY.values():
        files = src.discover()
        size = sum(f.stat().st_size for f in files if f.exists())
        rows.append({"source": src.name, "description": src.description, "files": len(files), "bytes": size})
    unparsed = []
    for name, rel in UNPARSED.items():
        p = HOME / rel
        if p.exists():
            size = p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            unparsed.append({"source": name, "path": str(p), "bytes": size})
    inv = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "parsed": rows, "unparsed": unparsed}
    save_json(home() / "inventory.json", inv)
    return inv


def _extract_file(name: str, path: str) -> tuple[str, str, list[dict], str | None]:
    try:
        return name, path, list(REGISTRY[name].extract(Path(path))), None
    except Exception as exc:  # a broken file must not stop the run
        return name, path, [], f"{type(exc).__name__}: {exc}"[:300]


def default_shell(r: dict) -> str | None:
    """The shell that executed the command, from the recording tool and platform."""
    if r.get("shell"):
        return r["shell"]
    tool = (r.get("tool") or "").lower()
    windows = bool(re.match(r"^[A-Za-z]:[\\/]", r.get("working_directory") or ""))
    if tool == "bash":
        return "bash"
    if r["source_type"] in ("codex", "opencode2", "cursor") or (r["source_type"] == "opencode" and tool == "shell"):
        return "powershell" if windows else "bash"
    return None


def normalize_ws(cmd: str) -> str:
    return re.sub(r"\s+", " ", cmd).strip()


def template_key(cmd: str) -> str:
    t = normalize_ws(cmd)
    t = UUID.sub("<uuid>", t)
    t = ISO.sub("<ts>", t)
    t = TEMP.sub(r"\1<tmp>", t)
    t = HEX.sub(lambda m: "<hex>" if re.search(r"\d", m.group(0)) and re.search(r"[a-f]", m.group(0), re.I) else m.group(0), t)
    return NUM.sub("0", t)


def hard_tags(raw: str, redacted: str, st) -> list[str]:
    tags = []
    if st.shell == "powershell" and len(raw) > 400:
        tags.append("long_powershell")
    if len(raw) > 1500:
        tags.append("very_long")
    if re.search(r"\"[^\"]*'[^']*'[^\"]*\"|'[^']*\"[^\"]*\"[^']*'|\\\"|`\"|\"\"", raw):
        tags.append("nested_quoting")
    if st.loops:
        tags.append("loop")
    if st.conditionals:
        tags.append("conditional")
    if st.pipelines:
        tags.append("pipeline")
    if st.segments > 1:
        tags.append("chained")
    if st.has_inline_script:
        tags.append("inline_script")
    if st.has_heredoc:
        tags.append("heredoc")
    if NATURAL.search(raw):
        tags.append("natural_language")
    if INJECTION.search(raw):
        tags.append("injection_like")
    if redacted != raw:
        tags.append("secret")
    if raw.count('"') % 2 or raw.count("(") != raw.count(")") or raw.count("{") != raw.count("}"):
        tags.append("malformed")
    if any(a.type == "other" for a in st.actions):
        tags.append("uncommon_tool")
    return tags


def extract(sources: list[str] | None = None, workers: int = 0) -> dict:
    names = sources or list(REGISTRY)
    jobs = [(n, str(f)) for n in names for f in REGISTRY[n].discover()]
    workers = workers or max(1, (os.cpu_count() or 4) - 2)
    t0 = time.time()
    per_source = collections.Counter()
    errors = []
    seen_ids: set[str] = set()
    out = private_dir() / "records.jsonl"
    tmp = out.with_suffix(".jsonl.tmp")
    total = 0
    import json
    with open(tmp, "w", encoding="utf-8", newline="\n") as w, ProcessPoolExecutor(workers) as pool:
        futures = [pool.submit(_extract_file, n, f) for n, f in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            name, path, recs, err = fut.result()
            if err:
                errors.append({"source": name, "file": path, "error": err})
            for r in recs:
                cmd = r.get("command_raw")
                if not isinstance(cmd, str) or not cmd.strip() or r["id"] in seen_ids:
                    continue
                seen_ids.add(r["id"])
                r["command_redacted"] = redact(cmd)
                r["preceding_context"] = redact(r["preceding_context"])
                r["following_context"] = redact(r["following_context"])
                r["existing_model_text"] = redact(r["existing_model_text"])
                w.write(json.dumps(r, ensure_ascii=False) + "\n")
                per_source[name] += 1
                total += 1
            if i % 200 == 0:
                print(f"  {i}/{len(jobs)} files, {total} records, {time.time() - t0:.0f}s", flush=True)
    os.replace(tmp, out)
    summary = {"files": len(jobs), "records": total, "per_source": dict(per_source), "errors": errors,
               "seconds": round(time.time() - t0, 1)}
    save_json(home() / "reports" / "extract_summary.json", summary)
    return summary


def dedupe() -> dict:
    groups: dict[str, dict] = {}
    exact = set()
    ws = set()
    n = 0
    for r in read_jsonl(private_dir() / "records.jsonl"):
        n += 1
        raw = r["command_raw"]
        exact.add(sha(raw))
        wsn = normalize_ws(raw)
        ws.add(sha(wsn))
        key = sha(template_key(raw))
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"id": f"cmd_{key}", "variants": collections.Counter(), "raw_by_variant": {},
                               "count": 0, "sources": collections.Counter(), "shell_hints": collections.Counter(),
                               "cwds": collections.Counter(), "existing_model_texts": collections.Counter(),
                               "exit_codes": collections.Counter(), "members": [], "first": None, "last": None,
                               "record_tags": collections.Counter(), "context": None}
        g["count"] += 1
        vk = sha(wsn)
        g["variants"][vk] += 1
        g["raw_by_variant"].setdefault(vk, r)
        g["sources"][r["source_type"]] += 1
        hint = default_shell(r)
        if hint:
            g["shell_hints"][hint] += 1
        if r.get("working_directory"):
            g["cwds"][r["working_directory"]] += 1
        if r.get("existing_model_text"):
            g["existing_model_texts"][r["existing_model_text"]] += 1
        g["exit_codes"][str(r.get("exit_code"))] += 1
        for t in r.get("tags") or []:
            g["record_tags"][t] += 1
        if len(g["members"]) < 25:
            g["members"].append(r["id"])
        ts = r.get("timestamp")
        if ts:
            g["first"] = min(g["first"] or ts, ts)
            g["last"] = max(g["last"] or ts, ts)

    rows = []
    for g in groups.values():
        top_variant = max(g["variants"].items(), key=lambda kv: (kv[1], -len(g["raw_by_variant"][kv[0]]["command_raw"])))[0]
        rep = g["raw_by_variant"][top_variant]
        raw = rep["command_raw"]
        red = redact(raw)
        hint = g["shell_hints"].most_common(1)[0][0] if g["shell_hints"] else None
        st = analyze(raw, hint)
        tags = hard_tags(raw, red, st)
        if len(raw) > MAX_COMMAND_CHARS:
            tags.append("over_length")
        rows.append({
            "id": g["id"], "count": g["count"], "exact_variants": len(g["variants"]),
            "shell": st.shell, "command_raw": raw, "command_redacted": red,
            "working_directory": redact(g["cwds"].most_common(1)[0][0]) if g["cwds"] else None,
            "preceding_context": rep["preceding_context"], "following_context": rep["following_context"],
            "existing_model_text": g["existing_model_texts"].most_common(1)[0][0] if g["existing_model_texts"] else None,
            "existing_model_texts": [t for t, _ in g["existing_model_texts"].most_common(5)],
            "exit_code": rep.get("exit_code"), "exit_codes": dict(g["exit_codes"]),
            "sources": dict(g["sources"]), "source_file": rep["source_file"], "source_type": rep["source_type"],
            "timestamp": g["first"], "last_seen": g["last"], "members": g["members"],
            "structure": st.to_dict(), "complexity": complexity(st, raw), "length": len(raw),
            "tags": sorted(set(tags) | set(g["record_tags"])),
            "template_hash": g["id"][4:],
        })
    rows.sort(key=lambda r: -r["count"])
    write_jsonl(private_dir() / "commands.jsonl", rows)
    write_jsonl(home() / "commands_redacted.jsonl",
                ({k: v for k, v in r.items() if k != "command_raw"} for r in rows))
    return {"records": n, "unique_exact": len(exact), "unique_whitespace": len(ws), "template_groups": len(rows)}


def _bucket(n: int) -> str:
    for edge in (40, 100, 250, 500, 1000, 2500, 6000):
        if n <= edge:
            return f"<={edge}"
    return ">6000"


def stats(dedup: dict) -> dict:
    rows = list(read_jsonl(home() / "commands_redacted.jsonl"))
    C = collections.Counter
    by_shell, by_len, by_cplx, by_action, by_tag, by_src, exes, by_month = C(), C(), C(), C(), C(), C(), C(), C()
    by_freq = C()
    weighted_shell = C()
    with_desc = 0
    for r in rows:
        by_shell[r["shell"]] += 1
        weighted_shell[r["shell"]] += r["count"]
        by_len[_bucket(r["length"])] += 1
        by_cplx[r["complexity"]] += 1
        for a in set(r["structure"]["action_types"]):
            by_action[a] += 1
        for a in r["structure"]["actions"][:1]:
            exes[a["exe"] + (" " + a["sub"] if a.get("sub") and a["type"] in ("git", "github", "package") else "")] += r["count"]
        for t in r["tags"]:
            by_tag[t] += 1
        for s in r["sources"]:
            by_src[s] += 1
        by_freq["1" if r["count"] == 1 else "2-4" if r["count"] < 5 else "5-19" if r["count"] < 20 else "20+"] += 1
        if r.get("timestamp"):
            by_month[str(r["timestamp"])[:7]] += 1
        with_desc += bool(r.get("existing_model_text"))
    top = [{"count": r["count"], "shell": r["shell"], "command": r["command_redacted"][:160]} for r in rows[:40]]
    rep = {"dedup": dedup, "groups": len(rows), "with_existing_model_text": with_desc,
           "shell": dict(by_shell), "shell_weighted_by_frequency": dict(weighted_shell),
           "length": dict(sorted(by_len.items(), key=lambda kv: int(re.sub(r"\D", "", kv[0])))),
           "complexity": dict(by_cplx), "action_types": dict(by_action.most_common()),
           "hard_tags": dict(by_tag.most_common()), "sources_groups": dict(by_src), "frequency": dict(by_freq),
           "first_executables": dict(exes.most_common(40)), "month": dict(sorted(by_month.items())), "top_templates": top}
    save_json(home() / "reports" / "mining_stats.json", rep)
    (home() / "reports" / "mining_stats.md").write_text(render_md(rep), encoding="utf-8")
    return rep


def render_md(rep: dict) -> str:
    def table(d: dict, title: str) -> str:
        lines = [f"### {title}", "", "| key | n |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in d.items()]
        return "\n".join(lines) + "\n"
    ex = rep.get("extract", {})
    parts = ["# Mining statistics", "",
             f"Records extracted: **{rep['dedup']['records']}**; unique exact: **{rep['dedup']['unique_exact']}**; "
             f"unique after whitespace: **{rep['dedup']['unique_whitespace']}**; template groups: **{rep['groups']}**; "
             f"groups with an existing agent description: **{rep['with_existing_model_text']}**.", ""]
    if ex:
        parts.append(table(ex.get("per_source", {}), "Records per source"))
    for key, title in (("sources_groups", "Groups per source"), ("shell", "Shell (groups)"),
                       ("shell_weighted_by_frequency", "Shell (executions)"), ("length", "Length (chars)"),
                       ("complexity", "Complexity"), ("frequency", "Group frequency"),
                       ("action_types", "Action types (groups containing)"), ("hard_tags", "Difficulty tags"),
                       ("first_executables", "First executable (executions)"), ("month", "First seen (month)")):
        parts.append(table(rep[key], title))
    parts += ["### Most frequent templates (redacted)", "", "| n | shell | command |", "|---:|---|---|"]
    parts += [f"| {t['count']} | {t['shell']} | `{t['command'].replace('|', '¦').replace('`', 'ˋ').replace(chr(10), ' ')}` |" for t in rep["top_templates"]]
    return "\n".join(parts) + "\n"


def run_all(sources: list[str] | None = None, skip_extract: bool = False) -> dict:
    import json
    if skip_extract:
        ex = json.loads((home() / "reports" / "extract_summary.json").read_text(encoding="utf-8"))
    else:
        inv = inventory()
        print("inventory:", {r["source"]: r["files"] for r in inv["parsed"]}, flush=True)
        ex = extract(sources)
    print("extract:", {k: v for k, v in ex.items() if k != "errors"}, "errors:", len(ex["errors"]), flush=True)
    dd = dedupe()
    print("dedupe:", dd, flush=True)
    rep = stats(dd)
    rep["extract"] = ex
    save_json(home() / "reports" / "mining_stats.json", rep)
    (home() / "reports" / "mining_stats.md").write_text(render_md(rep), encoding="utf-8")
    return rep
