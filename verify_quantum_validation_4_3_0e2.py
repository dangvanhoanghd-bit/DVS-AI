from __future__ import annotations
import hashlib, json, sys
from pathlib import Path


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def main(path: str) -> int:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = value.pop("self_sha256", "")
    actual = canonical_hash(value)
    print(json.dumps({"valid": expected == actual, "expected": expected, "actual": actual}, indent=2))
    return 0 if expected == actual else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
