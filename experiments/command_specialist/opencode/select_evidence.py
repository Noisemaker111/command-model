"""Select source indices from an already-authorized native host read (JSON stdin)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import predict
from contract import evidence_result


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.load(sys.stdin)
    case = {"kind": "evidence", "request": payload["request"],
            "output_lines": payload["output_lines"], "exit_code": 0,
            "truncated": payload["truncated"]}
    selection, timing = predict(payload["base_url"], payload["model"], case)
    try:
        evidence_result(selection, case)
    except (ValueError, TypeError) as error:
        print(json.dumps({"error": str(error), "timing": timing}))
        return
    print(json.dumps({"lines": selection["lines"], "timing": timing}))


if __name__ == "__main__":
    main()
