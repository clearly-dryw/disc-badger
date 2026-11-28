# SPDX-License-Identifier: GPL-3.0-or-later
"""Every command Disc Badger may send to a drive, and the allowlist.

The commands are SCSI commands: the command set computers use to control storage
devices, which optical drives understand whether they connect by SATA or USB.
`Drive._send` calls `check_allowed` on every command; anything the allowlist
refuses never reaches the drive. Each family of commands sharing an opcode is an
`Opcode` subclass, holding its layout, its rule and its commands.
"""

# Everything that can reach a drive is in this file, to be reviewed in one
# place. A wrong command can do lasting harm: leave a drive stuck until it is
# unplugged, lock its tray, change settings it keeps, or rewrite its firmware.
# One opcode can do both safe and harmful things (1Eh unlocks or locks the
# tray), so each has a rule allowing only the forms Disc Badger needs. A correct
# caller never breaks a rule; the check stops bugs, such as a command built from
# a bad value read off a damaged disc.
#
# Each family's docstring names the draft and section its layout comes from;
# `drive` lists the drafts with their links.

from dataclasses import dataclass
from typing import ClassVar

################################################################################
# The allowlist
################################################################################


@dataclass(frozen=True)
class DriveCommand:
    """One command a drive can be sent, and how long to wait for it.

    `cdb` is a SCSI Command Descriptor Block: the first byte (the opcode) names
    the command, the rest are its settings.
    """

    cdb: bytes
    # Timeouts are generous: a drive spinning up a damaged disc can take many
    # seconds to answer.
    timeout_s: int


class Opcode:
    """A family of commands sharing one opcode, and the rule they must pass.

    Defining a subclass adds its family to `ALLOWLIST`. A subclass sets `opcode`
    and defines `allows`; its docstring gives the command layout and the draft
    and section it comes from. Its commands follow the class.
    """

    # A family is only added once it is needed and understood (see the comments
    # at the top of this file). Its rule checks the CDB's length and every byte:
    # a field with a documented reason to vary, such as "answer at once", is
    # checked against its allowed values, and every other byte must be what Disc
    # Badger sends, usually zero. Reserved and vendor-specific bits may mean
    # anything to a drive's firmware, so they are never left unchecked. A family
    # names the bits its rule and commands use. Its commands are DriveCommand
    # constants, or functions that build them, at module level.

    opcode: ClassVar[int]
    """The first byte of every CDB in the family."""

    def __init_subclass__(cls) -> None:
        """Check the new family is complete, then add it to ALLOWLIST."""
        super().__init_subclass__()
        name = cls.__name__
        if "opcode" not in vars(cls):
            raise TypeError(f"{name} doesn't set its opcode")
        if "allows" not in vars(cls):
            raise TypeError(f"{name} doesn't define its allows rule")
        if cls.opcode in ALLOWLIST:
            other = ALLOWLIST[cls.opcode].__name__
            message = f"{name} reuses opcode {cls.opcode:02x} of {other}"
            raise TypeError(message)
        ALLOWLIST[cls.opcode] = cls

    @classmethod
    def allows(cls, cdb: bytes) -> bool:
        """Return whether this CDB may be sent; every subclass replaces it."""
        raise NotImplementedError


class CommandNotAllowedError(Exception):
    """A command that isn't on the allowlist; it is never sent."""


ALLOWLIST: dict[int, type[Opcode]] = {}
"""Every opcode Disc Badger may send, and its family.

Defining an `Opcode` subclass adds its family; don't add to it directly.
"""


def check_allowed(command: DriveCommand) -> None:
    """Raise CommandNotAllowedError, with the reason, if not allowed."""
    cdb = command.cdb
    if not cdb:
        reason = "it is empty"
    elif (family := ALLOWLIST.get(cdb[0])) is None:
        reason = f"opcode {cdb[0]:02x} has no Opcode class"
    elif not family.allows(cdb):
        reason = f"it breaks the rule of {family.__name__}"
    else:
        return
    raise CommandNotAllowedError(f"CDB [{cdb.hex(' ')}] not sent: {reason}")


################################################################################
# Command families, each followed by its commands
################################################################################


class OpcodePreventAllowMediumRemoval(Opcode):
    """PREVENT ALLOW MEDIUM REMOVAL (1Eh); MMC-5 section 6.14.

    Locks the tray, so the disc can't be removed while a program is using it, or
    unlocks it. While it's locked, the drive's eject button does nothing.
    Burning software, for example, locks the tray while it writes a disc.

    6 bytes:

    - bytes 1 to 3: reserved
    - byte 4, bits 7-2: reserved
    - byte 4, bit 1: Persistent (0: act on the ordinary lock; 1: act on the
      separate persistent lock)
    - byte 4, bit 0: Prevent (0: clear that lock; 1: set it)
    - byte 5: Control
    """

    opcode = 0x1E
    LENGTH = 6

    @classmethod
    def allows(cls, cdb: bytes) -> bool:
        """Allow clearing the ordinary lock only.

        Every byte after the opcode is 0: Persistent = 0 and Prevent = 0. Never
        set either lock, or clear the persistent one (nothing needs to).
        """
        return len(cdb) == cls.LENGTH and not any(cdb[1:])


UNLOCK = DriveCommand(
    cdb=bytes([OpcodePreventAllowMediumRemoval.opcode, 0, 0, 0, 0, 0]),
    timeout_s=10,
)
"""Unlock the tray, in case another program left it locked."""


class OpcodeStartStopUnit(Opcode):
    """START STOP UNIT (1Bh); MMC-5 section 6.40.

    Ejects or loads the disc, spins it up or stops it, or changes the drive's
    power state. Operating systems and players use it to eject a disc, and to
    stop it spinning when it isn't needed.

    6 bytes:

    - byte 1, bits 7-1: reserved
    - byte 1, bit 0: Immed (answer at once, before the action finishes)
    - byte 2: reserved
    - byte 3: Format-layer Number (used with FL), and reserved bits
    - byte 4, bits 7-4: Power Conditions (0: leave the power state alone;
      otherwise LoEj and Start are ignored)
    - byte 4, bit 3: reserved
    - byte 4, bit 2: FL (switch a hybrid disc to the Format-layer Number)
    - byte 4, bit 1: LoEj (load or eject the disc)
    - byte 4, bit 0: Start (with LoEj: 1 loads the disc, 0 ejects it; without
      LoEj: 1 spins the disc up, 0 stops it)
    - byte 5: Control
    """

    opcode = 0x1B
    LENGTH = 6
    LOEJ = 0b10

    @classmethod
    def allows(cls, cdb: bytes) -> bool:
        """Allow ejecting only, answering once the eject is done.

        LoEj = 1; every other bit is 0, Immed, Start, FL and Power Conditions
        included. Never load, stop or start the disc, switch its layer, or
        change the power state.
        """
        return (
            len(cdb) == cls.LENGTH
            and cdb[1] == 0
            and cdb[2] == 0
            and cdb[3] == 0
            and cdb[4] == cls.LOEJ
            and cdb[5] == 0
        )


EJECT = DriveCommand(
    cdb=bytes(
        [OpcodeStartStopUnit.opcode, 0, 0, 0, OpcodeStartStopUnit.LOEJ, 0],
    ),
    timeout_s=30,
)
"""Eject the disc, or the empty tray."""
