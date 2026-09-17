"""Wrapper for `cli.py extract_commands`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from cli import main

    main(["extract_commands", *sys.argv[1:]])
