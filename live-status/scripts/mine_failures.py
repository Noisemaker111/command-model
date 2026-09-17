"""Wrapper for `cli.py mine_failures`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from cli import main

    main(["mine_failures", *sys.argv[1:]])
