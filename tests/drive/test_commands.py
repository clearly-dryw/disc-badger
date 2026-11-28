# SPDX-License-Identifier: GPL-3.0-or-later
"""The allowlist: which commands may reach a drive, and why others can't."""

import pytest

from disc_badger.drive import commands
from disc_badger.drive.commands import (
    ALLOWLIST,
    CommandNotAllowedError,
    DriveCommand,
    Opcode,
    OpcodePreventAllowMediumRemoval,
    OpcodeStartStopUnit,
)

EVERY_COMMAND = [
    command
    for command in vars(commands).values()
    if isinstance(command, DriveCommand)
]

OPCODE_COUNT = 256  # an opcode is one byte

UNLOCK_RULE = "breaks the rule of OpcodePreventAllowMediumRemoval"
EJECT_RULE = "breaks the rule of OpcodeStartStopUnit"


def _any_rule(
    _cls: type[Opcode],
    cdb: bytes,
) -> bool:
    """Serve as a family's rule; it never runs in these tests."""
    return len(cdb) > 0


def test_every_family_is_on_the_allowlist() -> None:
    expected = {
        0x1E: OpcodePreventAllowMediumRemoval,
        0x1B: OpcodeStartStopUnit,
    }
    assert expected == ALLOWLIST


@pytest.mark.parametrize("command", EVERY_COMMAND)
def test_every_command_passes_its_familys_rule(command: DriveCommand) -> None:
    commands.check_allowed(command)


@pytest.mark.parametrize(
    ("cdb", "reason"),
    [
        ("1E 00 00 00 01 00", UNLOCK_RULE),  # lock the tray
        ("1E 00 00 00 03 00", UNLOCK_RULE),  # set the persistent lock
        ("1E 00 00 00 02 00", UNLOCK_RULE),  # clear it (nothing needs to)
        ("1E 00", UNLOCK_RULE),  # too short
        ("1E 01 00 00 00 00", UNLOCK_RULE),  # a reserved byte set
        ("1E 00 00 00 04 00", UNLOCK_RULE),  # a reserved bit in byte 4
        ("1E 00 00 00 00 80", UNLOCK_RULE),  # a vendor bit in the control byte
        ("1B 00 00 00 00 00", EJECT_RULE),  # stop the disc
        ("1B 00 00 00 01 00", EJECT_RULE),  # start the disc
        ("1B 00 00 00 03 00", EJECT_RULE),  # load the disc
        ("1B 00 00 01 07 00", EJECT_RULE),  # switch a hybrid disc's layer
        ("1B 00 00 00 32 00", EJECT_RULE),  # eject and change power state
        ("1B 00 00 00 10 00", EJECT_RULE),  # a reserved power condition, 1h
        ("1B 00 00 00 30 00", EJECT_RULE),  # standby
        ("1B 00 00 00 13 00", EJECT_RULE),  # load, power condition 1h
        ("1B 01 00 00 02 00", EJECT_RULE),  # eject, answering at once
        ("1B 02 00 00 02 00", EJECT_RULE),  # eject, a reserved bit in byte 1
        ("1B 00 01 00 02 00", EJECT_RULE),  # eject, reserved byte 2 set
        ("1B 00 00 01 02 00", EJECT_RULE),  # eject, a Format-layer Number
        ("1B 00 00 00 0A 00", EJECT_RULE),  # eject, reserved bit 3 of byte 4
        ("1B 00 00 00 02 80", EJECT_RULE),  # eject, a vendor bit in Control
        ("3B 05 00 00 00 00 00 00 00 00", "opcode 3b has no Opcode class"),
        ("", "it is empty"),
    ],
)
def test_other_commands_are_refused(
    cdb: str,
    reason: str,
) -> None:
    command = DriveCommand(cdb=bytes.fromhex(cdb), timeout_s=10)
    with pytest.raises(CommandNotAllowedError, match=reason):
        commands.check_allowed(command)


@pytest.mark.parametrize(
    "opcode",
    [opcode for opcode in range(OPCODE_COUNT) if opcode not in ALLOWLIST],
)
def test_no_other_opcode_is_allowed(opcode: int) -> None:
    command = DriveCommand(cdb=bytes([opcode, 0, 0, 0, 0, 0]), timeout_s=10)
    with pytest.raises(CommandNotAllowedError, match="has no Opcode class"):
        commands.check_allowed(command)


def test_the_timeout_doesnt_affect_the_allowlist() -> None:
    longer = DriveCommand(cdb=commands.EJECT.cdb, timeout_s=60)
    commands.check_allowed(longer)


# An incomplete family is refused when it is defined, before it is added to the
# allowlist, so these test classes leave ALLOWLIST as it was. type() defines
# each class, as a class statement would.


def test_a_family_must_set_its_opcode() -> None:
    with pytest.raises(TypeError, match="doesn't set its opcode"):
        # It raises, so there is no result to use.
        _ = type("NoOpcode", (Opcode,), {"allows": classmethod(_any_rule)})


def test_a_family_must_define_its_rule() -> None:
    with pytest.raises(TypeError, match="doesn't define its allows rule"):
        # It raises, so there is no result to use.
        _ = type("NoRule", (Opcode,), {"opcode": 0x12})


def test_a_family_cant_reuse_an_opcode() -> None:
    contents = {"opcode": 0x1B, "allows": classmethod(_any_rule)}
    with pytest.raises(TypeError, match="reuses opcode 1b of OpcodeStartStop"):
        # It raises, so there is no result to use.
        _ = type("Again", (Opcode,), contents)
