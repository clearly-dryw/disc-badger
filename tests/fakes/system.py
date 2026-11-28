# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for the operating system, as `system` sees it."""

import sys

import pytest

from disc_badger.drive.transport import system, transport_windows


def pretend_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the drive layer act as on Windows, on any operating system.

    Only the parts that work anywhere are available: a test can't connect to a
    drive this way.
    """
    # system loads the Windows modules only on Windows. transport_windows works
    # anywhere, so supply it; transport_windows_c doesn't, so it stays missing
    # elsewhere.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        system,
        "transport_windows",
        transport_windows,
        raising=False,
    )
