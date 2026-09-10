"""Request-local path bindings for an agent-to-specialist inspection handoff.

The caller supplies exact paths separately from intent. No filesystem crawling,
filename guessing, or model-generated reference registration happens here.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re

SLOT = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}")


@dataclass(frozen=True)
class BoundRequest:
    model_request: str
    display_request: str
    paths: tuple[tuple[str, str], ...]

    def case(self):
        return {"kind": "plan", "request": self.model_request,
                "path_refs": [ref for ref, _ in self.paths]}

    def resolve(self, prediction):
        if not isinstance(prediction, dict) or set(prediction) != {"op", "path", "value", "limit"}:
            raise ValueError("invalid bound plan fields")
        paths = dict(self.paths)
        ref = prediction["path"]
        if not isinstance(ref, str) or ref not in paths:
            raise ValueError("unknown file reference; no command executed")
        return {**prediction, "path": paths[ref]}


def bind_request(root: Path, request: str, targets: dict[str, str]) -> BoundRequest:
    """Replace explicit {{name}} slots without interpreting or rewriting paths."""
    root = root.resolve(strict=True)
    if not root.is_dir() or not isinstance(request, str) or not request.strip():
        raise ValueError("a directory root and nonempty request are required")
    if not isinstance(targets, dict) or not 1 <= len(targets) <= 16:
        raise ValueError("provide 1..16 named targets")
    refs, paths = {}, []
    for name, path in targets.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError("invalid target name")
        if not isinstance(path, str) or not path:
            raise ValueError("target path must be a nonempty string")
        relative = Path(path)
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise ValueError("target path must be relative to the selected root")
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root) or not resolved.exists():
            raise ValueError("target outside root or missing")
        ref = f"file_{len(paths) + 1}"
        refs[name] = ref
        paths.append((ref, path))
    matches = list(SLOT.finditer(request))
    if not matches or any(match[1] not in refs for match in matches):
        raise ValueError("request must use registered {{target}} names")
    # One pass: braces, quotes and reference-like text within a path stay literal.
    model_request = SLOT.sub(lambda match: json.dumps(refs[match[1]]), request)
    display_request = SLOT.sub(lambda match: json.dumps(targets[match[1]], ensure_ascii=False), request)
    return BoundRequest(model_request, display_request, tuple(paths))
