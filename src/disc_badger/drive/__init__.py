# SPDX-License-Identifier: GPL-3.0-or-later
"""The drive layer: `Drive`, one connected optical drive.

Modules outside this package use only what `__all__` lists: the `Drive` class
and its named operations, and the results and errors they return.
"""

# The drafts of the SCSI standards the drive layer is built from. Each module
# names the draft and section it relies on:
#
# - MMC-5 (MultiMedia Commands, for optical drives), revision 4:
#   https://www.13thmonkey.org/documentation/SCSI/mmc5r04.pdf
# - SPC-3 (SCSI Primary Commands, for every kind of device), revision 23:
#   https://www.13thmonkey.org/documentation/SCSI/spc3r23.pdf
# - MMC-3 (an earlier MultiMedia Commands), revision 10g:
#   https://archive.org/details/mmc3r10g

from typing import Self

from disc_badger.drive import commands
from disc_badger.drive.commands import DriveCommand
from disc_badger.drive.sense_data import SenseData
from disc_badger.drive.transport import (
    CommandResult,
    DriveAnswer,
    DriveConnectError,
    DriveConnectReason,
    OsFailure,
    OsFailureKind,
    Transport,
    system,
)

__all__ = [
    "CommandResult",
    "Drive",
    "DriveAnswer",
    "DriveConnectError",
    "DriveConnectReason",
    "OsFailure",
    "OsFailureKind",
    "SenseData",
]


class Drive:
    """One connected optical drive.

    Every command is checked against the allowlist. Use a `Drive` in a `with`
    block, so it's disconnected even when something fails.
    """

    def __init__(self, transport: Transport) -> None:
        """Wrap a transport; `connect` makes one for a real drive."""
        self._transport = transport

    @classmethod
    def connect(cls, name: str) -> Self:
        """Connect to a drive by name, in any form `normalize_name` accepts.

        Raise ValueError if the name can't be a drive, DriveConnectError if the
        drive can't be reached, or NotImplementedError if Disc Badger doesn't
        support this operating system.
        """
        return cls(system.connect(cls.normalize_name(name)))

    def disconnect(self) -> None:
        """Disconnect from the drive."""
        self._transport.disconnect()

    def __enter__(self) -> Self:
        """Start `with Drive.connect(...) as drive:`."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Disconnect at the end of `with`, even after an exception."""
        self.disconnect()

    def _send(self, command: DriveCommand) -> CommandResult:
        """Send one allowed command, or raise CommandNotAllowedError.

        This is the only way a command reaches the drive. The allowlist is in
        `commands`.
        """
        # Private, so callers outside Drive can only use its named operations,
        # such as eject: every command goes through a method this layer
        # designed, as well as the allowlist.
        commands.check_allowed(command)
        return self._transport.send(command)

    # Names --------------------------------------------------------------------

    @staticmethod
    def normalize_name(name: str) -> str:
        r"""Turn a drive name as typed into this operating system's form.

        Raise ValueError if it can't be a drive, or NotImplementedError if Disc
        Badger doesn't support this operating system. On each one:

        - Windows: `D`, `D:`, `D:\`, `d:` and `\\.\D:` all become `D:`.
        """
        return system.normalize_name(name)

    # Tray ---------------------------------------------------------------------

    def eject(self) -> CommandResult:
        """Unlock the tray, then eject; the result is the eject's.

        The eject is tried even if the unlock fails.
        """
        # Unlock first: a lock another program left behind is the usual reason a
        # drive's eject button stops working. The unlock's result isn't needed,
        # since the eject is sent either way.
        _ = self._send(commands.UNLOCK)
        return self._send(commands.EJECT)
