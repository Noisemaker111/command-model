"""Wrapper for `cli.py inventory_sources`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from cli import main

    main(["inventory_sources", *sys.argv[1:]])
