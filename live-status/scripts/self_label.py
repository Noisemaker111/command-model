"""Wrapper for `cli.py self_label`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from cli import main

    main(["self_label", *sys.argv[1:]])
