# SPDX-License-Identifier: GPL-3.0-or-later
"""The test stand-ins themselves behave as the tests rely on."""

import pytest

from disc_badger.drive.commands import EJECT
from tests.fakes import GOOD, TransportFake


def test_transport_fake_fails_when_it_has_no_answer_left() -> None:
    fake = TransportFake(GOOD)
    assert fake.send(EJECT) == GOOD
    with pytest.raises(AssertionError, match="no answer left for CDB"):
        # It raises, so there is no result to use.
        _ = fake.send(EJECT)


def test_transport_fake_reports_an_unused_answer() -> None:
    _ = TransportFake(GOOD)  # made, but never sent anything
    with pytest.raises(AssertionError, match="answers never used"):
        TransportFake.check_all_answered()


def test_transport_fake_refuses_commands_once_disconnected() -> None:
    fake = TransportFake()
    fake.disconnect()
    with pytest.raises(RuntimeError, match="disconnected"):
        # It raises, so there is no result to use.
        _ = fake.send(EJECT)
    assert fake.sent == []
