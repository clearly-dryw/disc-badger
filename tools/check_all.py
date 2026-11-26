# SPDX-License-Identifier: GPL-3.0-or-later
"""Run every check CI runs, so a pull request can pass the first time.

Run as `uv run python tools/check_all.py` before opening a pull request. It runs
each check even after one fails, then names the ones that failed, and exits with
1 if any did. It changes no files. The tests run once, on this system's Python;
CI also runs them on every supported system and Python.
"""

import argparse
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable

from exit_code import ExitCode

ROOT = pathlib.Path(__file__).resolve().parents[1]
"""The repository's top folder; every check runs from it."""

TESTS = "Tests"
"""The name of the check that runs the tests, which `--no-tests` skips."""

PYTHON_SUFFIX = ".py"
"""The suffix of the files that are Python code."""

PYRIGHT_PLATFORMS = {"Windows": "Windows", "Linux": "Linux", "macOS": "Darwin"}
"""Each system pyright checks the code for: its name, then pyright's."""

# Reports a check that can't run, with its traceback.
_logger = logging.getLogger(__name__)

# GitHub Actions folds the lines between ::group:: and ::endgroup:: under a
# heading.
_IN_GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def _passes(run: Callable[[], bool]) -> bool:
    """Run a check; return whether it passed, failing it if it can't run."""
    # Whatever goes wrong, such as git missing or a bug in a check, report it in
    # full and fail this check, so the others still run. The traceback shows a
    # bug as clearly as a crash would.
    try:
        return run()
    except Exception as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.rstrip())  # git's own reason
        _logger.exception("This check couldn't run")
        return False


def _run(*command: str) -> bool:
    """Run a program from ROOT; return whether it succeeded."""
    # Only Python itself, by full path, with fixed arguments and the names of
    # the repository's own files.
    return subprocess.run(command, cwd=ROOT, check=False).returncode == 0


def _python(*arguments: str) -> Callable[[], bool]:
    """Return a check that runs this Python with these arguments."""
    return lambda: _run(sys.executable, *arguments)


def _python_on_files(
    files: Callable[[], list[str]],
    *arguments: str,
) -> Callable[[], bool]:
    """Return a check that runs this Python on some of the repository's files.

    `files` lists them when the check runs; they're passed after `arguments`.
    """
    return lambda: _run(sys.executable, *arguments, *files())


def _start_group(name: str) -> None:
    """Print a check's heading, as a folding group in GitHub Actions."""
    # Flush, so the heading comes before the output of the check's program.
    if _IN_GITHUB_ACTIONS:
        print(f"::group::{name}", flush=True)
    else:
        print(f"== {name}", flush=True)


def _end_group() -> None:
    """End a check's folding group in GitHub Actions."""
    if _IN_GITHUB_ACTIONS:
        print("::endgroup::", flush=True)


def repository_files() -> list[str]:
    """Return the files git tracks, or would track, relative to ROOT.

    Ignored files are left out, and so are tracked files deleted from the
    working tree.
    """
    git = shutil.which("git")
    if git is None:
        raise FileNotFoundError("git isn't installed, or isn't on the PATH.")
    # Only git, by full path, with fixed arguments. With -z, names come
    # separated by null characters and exactly as they are, where git would
    # otherwise quote and escape unusual ones (`café.py` becomes
    # "caf\303\251.py"), so they'd match no file and slip past every check.
    listed = subprocess.run(
        [
            git,
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    ).stdout.split("\0")
    return sorted({name for name in listed if (ROOT / name).is_file()})


def python_files() -> list[str]:
    """Return the repository's Python files."""
    return [name for name in repository_files() if name.endswith(PYTHON_SUFFIX)]


def text_files() -> list[str]:
    """Return the files the text check reads: all but its exceptions."""
    with (ROOT / "pyproject.toml").open("rb") as settings:
        excluded = set(tomllib.load(settings)["tool"]["check-text"]["exclude"])
    return [name for name in repository_files() if name not in excluded]


def checks() -> list[tuple[str, Callable[[], bool]]]:
    """Return each check's name and the function that runs it, in order."""
    # Every file is checked unless .gitignore, or an exception in
    # pyproject.toml, leaves it out, so the checks that take files get them from
    # git rather than from a list of folders.
    #
    # The lock file must match pyproject.toml, and name only PyPI. ruff doesn't
    # re-wrap comments and docstrings, or read files other than Python, so the
    # text check does. pyright only checks the code for the system it's told
    # it's on, so it checks each one.
    return [
        (
            "File names",
            # After --, a name starting with - is read as a name, not an option.
            _python_on_files(
                repository_files,
                "tools/check_file_names.py",
                "--",
            ),
        ),
        ("Lock file", _python("tools/check_lock.py")),
        ("Formatting", _python("-m", "ruff", "format", "--check")),
        ("Lint", _python("-m", "ruff", "check")),
        ("Text", _python_on_files(text_files, "tools/check_text.py")),
        *[
            (
                f"Types ({name})",
                _python_on_files(
                    python_files,
                    "-m",
                    "pyright",
                    "--pythonplatform",
                    platform,
                ),
            )
            for name, platform in PYRIGHT_PLATFORMS.items()
        ],
        (TESTS, _python("-m", "pytest")),
    ]


def main(argv: list[str]) -> ExitCode:
    """Run the checks; return the exit code."""
    parser = argparse.ArgumentParser(
        prog="python tools/check_all.py",
        description="Run every check CI runs.",
    )
    # add_argument returns the new argument, which isn't needed.
    _ = parser.add_argument(
        "--no-tests",
        action="store_true",
        help="skip the tests, which CI runs in a job of their own",
    )
    options = parser.parse_args(argv)

    # Run every check, even after one fails, so all the problems show at once.
    failed: list[str] = []
    for name, run in checks():
        if options.no_tests and name == TESTS:
            continue
        _start_group(name)
        if not _passes(run):
            failed.append(name)
        _end_group()

    if failed:
        print(f"Failed: {', '.join(failed)}.")
        return ExitCode.PROBLEMS
    print("Every check passed.")
    return ExitCode.OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
