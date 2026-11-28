# SPDX-License-Identifier: GPL-3.0-or-later
"""What `system` checks before any transport is used."""

import sys

import pytest

from disc_badger.drive.transport.system import check_64_bit


def test_64_bit_python_is_accepted() -> None:
    check_64_bit()


def test_32_bit_python_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Look like 32-bit Python, where sys.maxsize is the largest 32-bit number.
    monkeypatch.setattr(sys, "maxsize", 2**31 - 1)
    with pytest.raises(RuntimeError, match="needs 64-bit Python, not 32-bit"):
        check_64_bit()
