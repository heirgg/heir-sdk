#!/usr/bin/env python3
"""Copy backend documents with explicit names and retain verifiable provenance."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {
    "openapi.json": "public-openapi.json",
    "stat-submission-openapi.json": "stat-submission-openapi.json",
    "builtin-gamemodes.json": "builtin-gamemodes.json",
    "stat-schemas.json": "stat-schemas.json",
}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def check_snapshot(root=ROOT):
    spec = root / "spec"
    expected = set(DOCUMENTS.values()) | {"type-names.json", "source.json"}
    unexpected = {path.name for path in spec.glob("*.json")} - expected
    if unexpected:
        raise ValueError(f"Unexpected spec files: {sorted(unexpected)}; use scripts/sync-spec.py.")
    manifest = json.loads((spec / "source.json").read_text())
    if set(manifest["sha256"]) != set(DOCUMENTS.values()):
        raise ValueError("The provenance manifest must cover every backend document.")
    for name, expected_hash in manifest["sha256"].items():
        content = (spec / name).read_bytes()
        json.loads(content)
        if digest(content) != expected_hash:
            raise ValueError(f"{name} differs from its recorded source; run the spec sync command.")
    return manifest


def synchronize(source, allow_dirty=False, check=False, root=ROOT):
    source = source.resolve()
    documents = {target: (source / original).read_bytes() for original, target in DOCUMENTS.items()}
    for name, content in documents.items():
        parsed = json.loads(content)
        if name.endswith("openapi.json") and not {"paths", "components"} <= parsed.keys():
            raise ValueError(f"{name} is not an OpenAPI contract.")
    if check:
        check_snapshot(root)
        changed = [name for name, content in documents.items() if (root / "spec" / name).read_bytes() != content]
        if changed:
            raise ValueError(f"Backend and SDK differ: {', '.join(changed)}")
        return
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    repository = Path(subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"], text=True).strip()).resolve()
    dirty = False
    # Compare bytes at HEAD rather than status: ignored/untracked inputs must not masquerade as a release.
    for original, target in DOCUMENTS.items():
        relative = (source / original).resolve().relative_to(repository)
        committed = subprocess.run(
            ["git", "-C", str(source), "show", f"{revision}:{relative.as_posix()}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        if committed.returncode or committed.stdout != documents[target]:
            dirty = True
    if dirty and not allow_dirty:
        raise ValueError("Source documents are uncommitted. Commit them first, or explicitly pass --allow-dirty for a candidate snapshot.")
    manifest = {
        "description": "Backend contract snapshot; hashes identify the exact input. This does not assert deployment parity.",
        "backendRevision": revision,
        "uncommittedSource": dirty,
        "sha256": {name: digest(content) for name, content in documents.items()},
    }
    for name, content in documents.items():
        (root / "spec" / name).write_bytes(content)
    (root / "spec" / "source.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Copied four backend documents. Regenerate and check all three SDKs before committing.")
    if dirty:
        print("Recorded an unreleased working-tree snapshot; verify the backend release before publishing.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", help="Backend docs/public-api directory")
    parser.add_argument("--check", action="store_true", help="Check hashes and, when supplied, compare the backend")
    parser.add_argument("--allow-dirty", action="store_true", help="Record explicitly unreleased backend documents")
    args = parser.parse_args()
    try:
        if args.source:
            synchronize(args.source, args.allow_dirty, args.check)
        elif args.check:
            check_snapshot()
        else:
            parser.error("Provide a source directory, or use --check to verify the local snapshot.")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
