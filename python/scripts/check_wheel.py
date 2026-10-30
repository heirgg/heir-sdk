"""Install the built wheel in an isolated environment and run its offline consumer checks."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum", action="store_true", help="Install the oldest declared runtime dependencies")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    wheels = list((root / "dist").glob("*.whl"))
    if len(wheels) != 1:
        parser.error("Expected exactly one wheel in dist/. Clean dist and run python -m build first.")
    requirements = [str(wheels[0])]
    if args.minimum:
        requirements += ["anyio==4.0.0", "httpx==0.27.0", "pydantic==2.7.0"]
    with tempfile.TemporaryDirectory(prefix="heir-wheel-") as directory:
        environment = Path(directory)
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", *requirements], check=True)
        subprocess.run([str(python), str(root / "scripts/smoke_installed.py")], cwd=environment, check=True)


if __name__ == "__main__":
    main()
