# SPDX-License-Identifier: GPL-3.0-or-later
"""A connected drive: ejecting, what it sends, disconnecting, drive names."""

import sys

import pytest

from disc_badger import drive
from disc_badger.drive import commands
from disc_badger.drive.commands import (
    EJECT,
    UNLOCK,
    CommandNotAllowedError,
    DriveCommand,
)
from disc_badger.drive.transport import system
from tests.fakes import (
    GOOD,
    OS_FAILED,
    REFUSED,
    TransportFake,
    pretend_windows,
)


def test_eject_unlocks_then_ejects() -> None:
    fake = TransportFake(GOOD, GOOD)
    assert drive.Drive(fake).eject() == GOOD
    assert fake.sent == [
        (bytes.fromhex("1E 00 00 00 00 00"), 10),
        (bytes.fromhex("1B 00 00 00 02 00"), 30),
    ]


def test_a_failed_unlock_doesnt_stop_the_eject() -> None:
    fake = TransportFake(REFUSED, GOOD)
    assert drive.Drive(fake).eject() == GOOD
    assert [cdb for cdb, _ in fake.sent] == [UNLOCK.cdb, EJECT.cdb]


def test_an_undelivered_unlock_doesnt_stop_the_eject() -> None:
    fake = TransportFake(OS_FAILED, GOOD)
    assert drive.Drive(fake).eject() == GOOD
    assert [cdb for cdb, _ in fake.sent] == [UNLOCK.cdb, EJECT.cdb]


def test_an_undelivered_eject_is_reported() -> None:
    fake = TransportFake(GOOD, OS_FAILED)
    assert drive.Drive(fake).eject() == OS_FAILED


def test_a_refused_command_is_never_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Make eject send a command the allowlist refuses: locking the tray.
    lock = DriveCommand(cdb=bytes.fromhex("1E 00 00 00 01 00"), timeout_s=10)
    monkeypatch.setattr(commands, "EJECT", lock)
    fake = TransportFake(GOOD)  # only the unlock is sent
    with pytest.raises(CommandNotAllowedError):
        # It raises, so there is no result to use.
        _ = drive.Drive(fake).eject()
    # Only the unlock was sent; the lock never reached the drive.
    assert fake.sent == [(UNLOCK.cdb, UNLOCK.timeout_s)]


def test_each_command_keeps_its_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    longer = DriveCommand(cdb=EJECT.cdb, timeout_s=60)
    monkeypatch.setattr(commands, "EJECT", longer)
    fake = TransportFake(GOOD, GOOD)
    # The test checks what the drive was sent, not what it answered.
    _ = drive.Drive(fake).eject()
    assert fake.sent[-1] == (EJECT.cdb, 60)


def test_with_disconnects_the_drive() -> None:
    fake = TransportFake()
    with drive.Drive(fake):
        assert not fake.disconnected
    assert fake.disconnected


def test_with_disconnects_the_drive_after_an_exception() -> None:
    fake = TransportFake()
    with pytest.raises(KeyboardInterrupt), drive.Drive(fake):
        raise KeyboardInterrupt  # such as the user pressing Ctrl+C
    assert fake.disconnected


def test_windows_drive_names_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pretend_windows(monkeypatch)
    assert drive.Drive.normalize_name("d") == "D:"


def test_connect_normalizes_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pretend_windows(monkeypatch)
    names: list[str] = []

    def record(drive_name: str) -> TransportFake:
        names.append(drive_name)
        return TransportFake()

    # Stand in for connecting through a transport, so no real drive is needed.
    monkeypatch.setattr(system, "connect", record)
    _ = drive.Drive.connect("d")  # the drive itself isn't needed
    assert names == ["D:"]


def test_connect_refuses_a_name_that_cant_be_a_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pretend_windows(monkeypatch)
    with pytest.raises(ValueError, match="isn't a drive letter"):
        # It raises, so there is no result to use.
        _ = drive.Drive.connect("D:\\Videos")


def test_an_unsupported_system_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "FakeOS")
    with pytest.raises(NotImplementedError, match="doesn't support FakeOS"):
        # It raises, so there is no result to use.
        _ = drive.Drive.normalize_name("D:")
    with pytest.raises(NotImplementedError, match="doesn't support FakeOS"):
        # It raises, so there is no result to use.
        _ = drive.Drive.connect("D:")
