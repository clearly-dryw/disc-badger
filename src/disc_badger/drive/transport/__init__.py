# SPDX-License-Identifier: GPL-3.0-or-later
"""The drive layer's backend: transports, which carry commands to a drive.

`Transport` is the interface every transport follows. `system` picks the
transport for the operating system Disc Badger is running on.

Each operating system has two modules here: `transport_<system>`, with its
transport (such as `TransportWindows`) and everything it needs that works on any
system, and `transport_<system>_c`, with only the calls into that system's C
functions, which loads only on that system.

Modules outside the drive layer use `Drive` instead; only `Drive` and the
transports use this package directly.
"""

from dataclasses import dataclass
from enum import Enum, unique
from typing import Protocol

from disc_badger.drive.commands import DriveCommand
from disc_badger.drive.scsi_status import ScsiStatus, scsi_status_meaning
from disc_badger.drive.sense_data import SenseData

__all__ = [
    "CommandResult",
    "DriveAnswer",
    "DriveConnectError",
    "DriveConnectReason",
    "OsFailure",
    "OsFailureKind",
    "Transport",
]


@unique
class DriveConnectReason(Enum):
    """Why `DriveConnectError` was raised, the same on every system."""

    NO_SUCH_DRIVE = "no such drive"
    NOT_OPTICAL = "not an optical drive"
    REFUSED = "refused"
    DENIED = "access denied"
    UNRECOGNIZED = "unrecognized"


class DriveConnectError(Exception):
    """Disc Badger couldn't connect to a drive.

    `reason` says why, the same on every operating system. `os_report` is what
    the system reported, in its own form, or None when it reported nothing:
    either an error, whose number is `os_error` and whose meaning is `reason`
    ("Windows error 5"), or an answer that says its own meaning ("Windows drive
    type 3: fixed drive, such as a hard disk"), when `os_error` is None.
    """

    def __init__(
        self,
        drive_name: str,
        os_error: int | None,
        os_report: str | None,
        reason: DriveConnectReason,
    ) -> None:
        """Record the drive, what the system reported and what it means."""
        if os_error is not None and os_report is None:
            raise ValueError("an os_error needs an os_report")
        self.drive_name = drive_name
        self.os_error = os_error
        self.os_report = os_report
        self.reason = reason
        message = f"couldn't connect to {drive_name} ({self.failure_reason()})"
        super().__init__(message)

    def failure_reason(self) -> str:
        """Return why, after what the system reported, if anything.

        For example "Windows error 5: access denied", "Windows drive type 3:
        fixed drive, such as a hard disk", or "not an optical drive".
        """
        if self.os_report is None:
            return self.reason.value
        if self.os_error is None:
            return self.os_report  # it says its own meaning
        return f"{self.os_report}: {self.reason.value}"


@unique
class OsFailureKind(Enum):
    """What an `OsFailure` means, the same on every operating system.

    Each value is what the failure means to a user, in plain words. `INVALID`
    means a malformed or unsupported request: a bug in Disc Badger.
    `UNRECOGNIZED` is a failure the transport doesn't know, such as an error
    code no table lists; it's handled like `TRANSPORT`.
    """

    TIMEOUT = "the drive didn't answer in time"
    DENIED = "the operating system didn't allow the command"
    GONE = "the drive was disconnected"
    NO_MEDIUM = "there's no disc in the drive"
    INVALID = "the operating system rejected the request"
    TRANSPORT = "the connection to the drive failed"
    UNRECOGNIZED = "unrecognized"


@dataclass(frozen=True)
class OsFailure:
    """Why a command got no answer from the drive, as the system reported it.

    Either the call to the operating system failed, or it reported a fault on
    the way to the drive (such as a Linux host status).
    """

    kind: OsFailureKind
    """What it means, the same on every system; Disc Badger acts on this."""
    os_error: int
    """The system's own number for it, for logs."""
    os_report: str
    """The system's name for `os_error`, such as "Windows error 121"."""

    def succeeded(self) -> bool:
        """Return False: a command that got no answer didn't work."""
        return False

    def failure_reason(self) -> str:
        """Return why the command failed: the system's report, then its meaning.

        For example "Windows error 121: the drive didn't answer in time".
        """
        return f"{self.os_report}: {self.kind.value}"


@dataclass(frozen=True)
class DriveAnswer:
    """The drive's answer to a command: its status, and any sense data."""

    scsi_status: int
    """The SCSI status, as a plain number.

    A drive may return values `ScsiStatus` doesn't name.
    """
    sense_data: SenseData | None
    """The drive's report on the command, or None when it sent none."""

    def succeeded(self) -> bool:
        """Return whether the command worked: the drive answered GOOD."""
        return self.scsi_status == ScsiStatus.GOOD

    def failure_reason(self) -> str:
        """Return why the command failed; raise ValueError if it succeeded.

        The drive's report comes first, then what it means in plain words:
        "sense 5/53/02: the drive rejected the request", "SCSI status 0x08: the
        drive was busy".
        """
        if self.succeeded():
            raise ValueError("the command succeeded: no failure reason")
        # With CHECK CONDITION, the sense data says why when it gives a sense
        # key. Otherwise the status itself is the report.
        if (
            self.scsi_status == ScsiStatus.CHECK_CONDITION
            and self.sense_data is not None
        ):
            sense_report = self.sense_data.sense_report()
            sense_key_meaning = self.sense_data.sense_key_meaning()
            if sense_report is not None and sense_key_meaning is not None:
                return f"{sense_report}: {sense_key_meaning}"
        meaning = scsi_status_meaning(self.scsi_status)
        return f"SCSI status 0x{self.scsi_status:02X}: {meaning}"


type CommandResult = DriveAnswer | OsFailure
"""What came back from one command: the drive's answer, or why there was none.

Both have `succeeded` and `failure_reason`, so a caller that only needs to know
whether the command worked, and why not, doesn't have to ask which one it got.
"""


class Transport(Protocol):
    """A connected drive that can run one command without data."""

    def disconnect(self) -> None:
        """Give up the connection; calling it again does nothing."""
        ...

    def send(self, command: DriveCommand) -> CommandResult:
        """Send one command and return what came back.

        Raise RuntimeError if disconnected.
        """
        ...
