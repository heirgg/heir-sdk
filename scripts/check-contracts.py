#!/usr/bin/env python3
"""Ensure the shared consumer fixtures exercise every documented operation."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    operations = {}
    for name in ("public-openapi.json", "stat-submission-openapi.json"):
        document = json.loads((root / "spec" / name).read_text())
        for path, methods in document["paths"].items():
            for method, operation in methods.items():
                if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                    continue
                identifier = operation["operationId"]
                if identifier in operations:
                    raise ValueError(f"Duplicate operationId in specs: {identifier}")
                operations[identifier] = (method.upper(), path)
    cases = json.loads((root / "tests" / "contracts.json").read_text())["cases"]
    identifiers = [case["operationId"] for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate contract fixture operationId")
    if set(identifiers) != set(operations):
        raise ValueError(f"Fixture coverage differs: {set(identifiers) ^ set(operations)}")
    for case in cases:
        method, path = operations[case["operationId"]]
        pattern = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path))
        if method != case["method"] or not re.fullmatch(pattern, case["path"]):
            raise ValueError(f"Fixture route mismatch: {case['operationId']}")
        if not isinstance(case.get("responseBody"), dict):
            raise ValueError(f"Missing response object: {case['operationId']}")
    print(f"Shared fixtures cover all {len(cases)} operations.")


if __name__ == "__main__":
    check()
