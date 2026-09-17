"""Wrapper for `cli.py benchmark_base_models`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from cli import main

    main(["benchmark_base_models", *sys.argv[1:]])
