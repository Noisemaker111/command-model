"""Wrapper for `cli.py serve`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from cli import main

    main(["serve", *sys.argv[1:]])
