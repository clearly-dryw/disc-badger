# SPDX-License-Identifier: GPL-3.0-or-later
"""The exit codes the developer tools return."""

# These are separate from Disc Badger's own exit codes, in
# disc_badger.cli.exit_code, on purpose: those are part of the product's
# interface and mean different things, and the tools must run even when the
# product's code is broken. Both use 0 for success and 2 for a wrong command
# line, as almost every program does.

import enum


@enum.unique
class ExitCode(enum.IntEnum):
    """How a developer tool ended."""

    OK = 0
    """Every check passed."""

    PROBLEMS = 1
    """The check found problems, each printed with its reason."""

    USAGE = 2
    """The command line was wrong, as for argparse."""
