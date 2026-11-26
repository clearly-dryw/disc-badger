# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that file and folder names keep to the rule in STYLE.md.

Run as `python tools/check_file_names.py PATH ...`, with paths written as git
writes them, folders separated by `/`. It prints each name that breaks the rule,
and exits with 1 if any do.
"""

import argparse
import re
import sys

from exit_code import ExitCode

# A file or folder name: ASCII letters, digits, ".", "_" and "-", not starting
# with "-". Other names cause trouble across systems and tools: macOS and
# Windows store accented letters differently, some tools mangle them, scripts
# trip over spaces, and a leading "-" makes a name look like an option.
_NAME_PART = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*")


def bad_file_names(names: list[str]) -> list[str]:
    """Return the names that break the rule."""
    return [
        name
        for name in names
        if not all(_NAME_PART.fullmatch(part) for part in name.split("/"))
    ]


def main(argv: list[str]) -> ExitCode:
    """Check the given names; return the exit code."""
    parser = argparse.ArgumentParser(
        prog="python tools/check_file_names.py",
        description="Check file and folder names.",
    )
    # add_argument returns the new argument, which isn't needed.
    _ = parser.add_argument("paths", nargs="*", metavar="PATH")
    options = parser.parse_args(argv)
    bad = bad_file_names(options.paths)
    for name in bad:
        print(
            f"{name}: rename this file; names use only ASCII letters, digits, "
            "`.`, `_` and `-`, and don't start with `-`",
        )
    return ExitCode.PROBLEMS if bad else ExitCode.OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
