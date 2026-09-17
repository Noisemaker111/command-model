"""Wrapper for `cli.py judge_labels`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from cli import main

    main(["judge_labels", *sys.argv[1:]])
