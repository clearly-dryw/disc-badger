# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks pytest runs around every test.

pytest finds fixtures shared by every test only in a file of this name.
"""

from collections.abc import Iterator

import pytest

from tests.fakes import TransportFake


@pytest.fixture(autouse=True)
def every_fake_answer_is_used() -> Iterator[None]:
    """Fail a test that leaves a `TransportFake` answer unused."""
    TransportFake.made.clear()  # fakes from before this test aren't its own
    yield
    TransportFake.check_all_answered()
