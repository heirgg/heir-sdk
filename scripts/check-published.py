#!/usr/bin/env python3
"""Allow release retries only when already-published artifacts match exactly."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.request


def check(package, version, directory):
    if package == "typescript":
        url = f"https://registry.npmjs.org/@heirgg%2fsdk/{version}"
        files = list(directory.glob("*.tgz"))
    else:
        url = f"https://pypi.org/pypi/heir-sdk/{version}/json"
        files = list(directory.glob("*.whl")) + list(directory.glob("*.tar.gz"))
    if not files or (package == "typescript" and len(files) != 1):
        raise ValueError("Expected the exact validated package artifacts.")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            record = json.load(response)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            return True
        raise
    if package == "typescript":
        raw = files[0].read_bytes()
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
        if record["dist"].get("integrity") != integrity:
            raise ValueError("The npm version exists with different bytes; never overwrite or silently accept it.")
        return False
    published = {item["filename"]: item["digests"]["sha256"] for item in record["urls"]}
    missing = False
    for file in files:
        if file.name not in published:
            missing = True
        elif published[file.name] != hashlib.sha256(file.read_bytes()).hexdigest():
            raise ValueError(f"PyPI already has different bytes for {file.name}.")
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", choices=("typescript", "python"))
    parser.add_argument("version")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if not args.version or any(char not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-" for char in args.version):
        parser.error("Invalid version")
    publish = check(args.package, args.version, args.directory)
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"publish={str(publish).lower()}\n")
    print("Unpublished artifacts remain." if publish else "Exact artifacts already published; resuming release notes.")


if __name__ == "__main__":
    main()
