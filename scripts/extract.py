"""Compatibility entry point for Shell Gatherer; preserves the original CLI."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "skills/shell-gatherer/scripts/gather.py"), run_name="__main__")
