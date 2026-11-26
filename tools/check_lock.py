# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that the lock file matches pyproject.toml and takes all from PyPI.

Run as `python tools/check_lock.py`. It prints each problem, and exits with 1 if
there are any. It changes no files.
"""

# uv checks each file's hash as it installs it, but downloads it from whatever
# address uv.lock gives. A changed lock file could name a file of the same name
# on another server, with that file's hash, so this check allows only PyPI.

import argparse
import pathlib
import shutil
import subprocess
import sys
import tomllib
from typing import Any

from exit_code import ExitCode

ROOT = pathlib.Path(__file__).resolve().parents[1]
"""The repository's top folder, where the lock file and pyproject.toml are."""

LOCK_FILE = "uv.lock"
"""The lock file, relative to ROOT."""

PYPI_INDEX = "https://pypi.org/simple"
"""The package index every locked package must come from."""

PYPI_FILES = "https://files.pythonhosted.org/"
"""The start of the address of every file PyPI serves."""

HASH_PREFIX = "sha256:"
"""The start of every locked file's hash."""

# How uv.lock records Disc Badger itself, installed from the repository.
_PROJECT_SOURCE = {"editable": "."}


def _matches_pyproject() -> bool:
    """Return whether uv finds the lock file up to date; uv says why not."""
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError("uv isn't installed, or isn't on the PATH.")
    # Only uv, by full path, with fixed arguments.
    checked = subprocess.run(
        [uv, "lock", "--check"],
        cwd=ROOT,
        check=False,
    )
    return checked.returncode == 0


def _project_name() -> str:
    """Return the project's name, from pyproject.toml."""
    with (ROOT / "pyproject.toml").open("rb") as settings:
        return tomllib.load(settings)["project"]["name"]


def _files(package: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the files the lock file records for a package."""
    sdist = package.get("sdist")
    return [*([sdist] if sdist else []), *package.get("wheels", [])]


def outside_pypi(
    lock_text: str,
    project: str,
) -> list[str]:
    """Return a problem for each package or file not from PyPI, or unhashed.

    `project` is the name of the project itself, installed from the repository.
    """
    problems: list[str] = []
    for package in tomllib.loads(lock_text).get("package", []):
        name = package["name"]
        source = package.get("source")
        if name == project and source == _PROJECT_SOURCE:
            continue
        if source != {"registry": PYPI_INDEX}:
            problems.append(f"{name} comes from {source}, not from PyPI.")
            continue
        for file in _files(package):
            url = file.get("url", "")
            if not url.startswith(PYPI_FILES):
                problems.append(f"{name}: {url!r} isn't a file on PyPI.")
            if not file.get("hash", "").startswith(HASH_PREFIX):
                problems.append(f"{name}: {url!r} has no SHA-256 hash.")
    return problems


def main(argv: list[str]) -> ExitCode:
    """Check the lock file; return the exit code."""
    parser = argparse.ArgumentParser(
        prog="python tools/check_lock.py",
        description="Check the lock file against pyproject.toml and PyPI.",
    )
    _ = parser.parse_args(argv)  # only --help; the options aren't needed
    matches = _matches_pyproject()
    problems = outside_pypi(
        lock_text=(ROOT / LOCK_FILE).read_text(encoding="utf-8"),
        project=_project_name(),
    )
    for problem in problems:
        print(f"{LOCK_FILE}: {problem}")
    if problems:
        # Plain `uv lock` keeps the addresses the lock file gives; --refresh
        # fetches them from PyPI again.
        print(
            "Every package must come from PyPI, with a hash. "
            "Regenerate the lock file with:\n"
            "  uv lock --refresh",
        )
    return ExitCode.OK if matches and not problems else ExitCode.PROBLEMS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
