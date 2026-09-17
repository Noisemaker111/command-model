"""Live-status pipeline CLI. Run `python live-status/cli.py <step> --help`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:6000])


def cmd_inventory_sources(a):
    from data_miner.mine import inventory
    _print(inventory())


def cmd_extract_commands(a):
    from data_miner.mine import run_all
    rep = run_all(a.source or None, skip_extract=a.skip_extract)
    _print({k: rep[k] for k in ("dedup", "shell", "complexity", "hard_tags")})


def cmd_redact_dataset(a):
    from redaction.apply import redact_file
    _print(redact_file(Path(a.input), Path(a.output)))


def cmd_generate_labels(a):
    from labeling.teacher import generate
    _print(generate(limit=a.limit, batch=a.batch, model=a.model, workers=a.workers, ids_file=a.ids))


def cmd_judge_labels(a):
    from judging.judge import judge_all
    _print(judge_all(limit=a.limit, batch=a.batch, model=a.model, workers=a.workers))


def cmd_build_dataset(a):
    from dataset_build.build import build
    _print(build(seed=a.seed, version=a.version))


def cmd_benchmark_base_models(a):
    from benchmarks.baseline import run
    _print(run(models=a.models, split=a.split, limit=a.limit, judge=not a.no_judge, prompt=a.prompt))


def cmd_train(a):
    from training.train import main as train_main
    train_main(a.rest)


def cmd_evaluate(a):
    from evaluation.evaluate import main as eval_main
    eval_main(a.rest)


def cmd_export_gguf(a):
    from training.export_gguf import main as export_main
    export_main(a.rest)


def cmd_serve(a):
    from api.server import main as serve_main
    serve_main(a.rest)


def cmd_mine_failures(a):
    from evaluation.active import main as active_main
    active_main(a.rest)


def cmd_run_full_pipeline(a):
    from pipeline import run
    _print(run(a))


PASSTHROUGH = {"train": cmd_train, "evaluate": cmd_evaluate, "export_gguf": cmd_export_gguf,
               "serve": cmd_serve, "mine_failures": cmd_mine_failures}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PASSTHROUGH:
        return PASSTHROUGH[argv[0]](argparse.Namespace(rest=argv[1:]))
    p = argparse.ArgumentParser(prog="live-status")
    sub = p.add_subparsers(dest="step", required=True)
    sub.add_parser("inventory_sources").set_defaults(fn=cmd_inventory_sources)
    s = sub.add_parser("extract_commands"); s.add_argument("--source", action="append")
    s.add_argument("--skip-extract", action="store_true", help="re-run dedup/stats on existing records")
    s.set_defaults(fn=cmd_extract_commands)
    s = sub.add_parser("redact_dataset"); s.add_argument("input"); s.add_argument("output"); s.set_defaults(fn=cmd_redact_dataset)
    for name, fn in (("generate_labels", cmd_generate_labels), ("judge_labels", cmd_judge_labels)):
        s = sub.add_parser(name)
        s.add_argument("--limit", type=int, default=0)
        s.add_argument("--batch", type=int, default=20 if name == "generate_labels" else 8)
        s.add_argument("--workers", type=int, default=3, help="parallel Opus requests; >4 trips the subscription rate limit")
        s.add_argument("--model", default="claude-opus-5")
        if name == "generate_labels":
            s.add_argument("--ids", help="file of command ids to label (e.g. mined failures)")
        s.set_defaults(fn=fn)
    s = sub.add_parser("build_dataset"); s.add_argument("--seed", type=int, default=20260916); s.add_argument("--version", default="v1"); s.set_defaults(fn=cmd_build_dataset)
    s = sub.add_parser("benchmark_base_models")
    s.add_argument("--models", nargs="+", required=True)
    s.add_argument("--split", default="test")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--prompt", choices=["instruct", "plain"], default="instruct")
    s.add_argument("--no-judge", action="store_true")
    s.set_defaults(fn=cmd_benchmark_base_models)
    for name in PASSTHROUGH:
        sub.add_parser(name, help=f"see `{name} --help`")
    s = sub.add_parser("run_full_pipeline")
    s.add_argument("--label-limit", type=int, default=0)
    s.add_argument("--skip-mining", action="store_true")
    s.set_defaults(fn=cmd_run_full_pipeline)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
