#!/usr/bin/env python3
"""Validate release versions; --preflight is read-only and never creates/pushes a tag."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?")
PYTHON_VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:(?:a|b|rc)\d+|\.dev\d+)?")


def validate(package, tag, root=ROOT):
    prefix = f"{package}/v"
    if not tag.startswith(prefix):
        raise ValueError(f"Expected a {prefix}… tag")
    version = tag[len(prefix):]
    pattern = PYTHON_VERSION if package == "python" else SEMVER
    if not pattern.fullmatch(version):
        raise ValueError("Use X.Y.Z or a supported prerelease version; build metadata is not supported.")
    if package != "python" and "-" in version:
        identifiers = version.split("-", 1)[1].split(".")
        if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in identifiers):
            raise ValueError("Numeric prerelease identifiers must not have leading zeros.")
    if package == "typescript":
        manifest = json.loads((root / "typescript/package.json").read_text())["version"]
        source = (root / "typescript/src/version.ts").read_text()
        constant = re.search(r'VERSION\s*=\s*"([^"]+)"', source).group(1)
    elif package == "python":
        manifest = re.search(r'^version\s*=\s*"([^"]+)"', (root / "python/pyproject.toml").read_text(), re.M).group(1)
        constant = re.search(r'__version__\s*=\s*"([^"]+)"', (root / "python/src/heir/_version.py").read_text()).group(1)
    else:
        manifest = re.search(r'const Version = "([^"]+)"', (root / "go/version.go").read_text()).group(1)
        constant = manifest
        if int(version.split(".")[0]) >= 2:
            raise ValueError("Go major versions 2+ need a matching module path and migration before release.")
    if version != manifest or version != constant:
        raise ValueError(f"Tag {version}, manifest {manifest}, and version constant {constant} must agree.")
    prerelease = not bool(re.fullmatch(r"\d+\.\d+\.\d+", version))
    return {"version": version, "prerelease": str(prerelease).lower(), "channel": "next" if prerelease else "latest"}


def preflight(root=ROOT):
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()
    if git("status", "--porcelain"):
        raise ValueError("Commit the final changes before preparing a release tag.")
    if git("branch", "--show-current") != "main":
        raise ValueError("Prepare a release from main.")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        raise ValueError("Fetch origin and verify HEAD is the reviewed origin/main commit.")
    subprocess.run(["python3", str(root / "scripts/sync-spec.py"), "--check"], check=True)
    subprocess.run(["python3", str(root / "scripts/check-contracts.py")], check=True)
    snapshot = json.loads((root / "spec/source.json").read_text())
    if snapshot["uncommittedSource"]:
        raise ValueError("The backend snapshot is unreleased. Sync from its committed release before tagging.")
    print("Local release preflight passed. Confirm the exact commit's CI and registry setup before pushing a tag.")


def require_main(tag, root=ROOT):
    """Verify the checked-out tag against origin/main fetched by the CI checkout.

    This is defense in depth. Remote tag rules and publishing approvals must
    restrict who can release, since a tag can also change this check's code.
    """
    def commit(ref):
        try:
            return subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
                text=True, stderr=subprocess.PIPE,
            ).strip()
        except subprocess.CalledProcessError as error:
            raise ValueError("Fetch origin/main and the exact release tag before verifying release ancestry.") from error

    head = commit("HEAD")
    tagged = commit(f"refs/tags/{tag}")
    main = commit("refs/remotes/origin/main")
    if head != tagged:
        raise ValueError(f"HEAD does not match the commit referenced by release tag {tag}.")
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", head, main],
        capture_output=True, text=True,
    )
    if result.returncode == 1:
        raise ValueError(f"Release tag {tag} is not an ancestor of fetched origin/main.")
    if result.returncode != 0:
        raise ValueError("Could not verify release ancestry; fetch complete origin/main history before retrying.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", choices=("typescript", "python", "go"))
    parser.add_argument("tag")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--require-committed-spec", action="store_true")
    parser.add_argument("--require-main", action="store_true", help="Require HEAD to match the release tag and be an ancestor of fetched origin/main")
    args = parser.parse_args()
    try:
        result = validate(args.package, args.tag)
        if args.require_main:
            require_main(args.tag)
        if args.require_committed_spec:
            subprocess.run(["python3", str(ROOT / "scripts/sync-spec.py"), "--check"], check=True)
            if json.loads((ROOT / "spec/source.json").read_text())["uncommittedSource"]:
                raise ValueError("Sync the spec from its committed backend release before publishing.")
        if args.preflight:
            preflight()
        if args.github_output:
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.writelines(f"{key}={value}\n" for key, value in result.items())
        print(json.dumps(result))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
