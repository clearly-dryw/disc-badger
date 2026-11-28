# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows: SCSI pass-through to a drive, `TransportWindows`.

Everything here works on any operating system, so the tests check it everywhere.
The calls into Windows itself are in `transport_windows_c`, which `system`
passes to `TransportWindows`.
"""

# Where the Windows values below come from. Microsoft documents most of them:
#
# - "Defining I/O Control Codes", the CTL_CODE formula:
#   https://learn.microsoft.com/windows-hardware/drivers/kernel/defining-i-o-control-codes
# - "Specifying Device Types", FILE_DEVICE_CONTROLLER:
#   https://learn.microsoft.com/windows-hardware/drivers/kernel/specifying-device-types
# - "Generic Access Rights", GENERIC_READ and GENERIC_WRITE:
#   https://learn.microsoft.com/windows/win32/secauthz/generic-access-rights
# - "CreateFileW", FILE_SHARE_READ, FILE_SHARE_WRITE and OPEN_EXISTING:
#   https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
#
# The rest appear only in the Windows SDK's headers (ntddscsi.h, devioctl.h);
# Microsoft's windows-sys bindings, generated from the SDK, give the same
# values: https://docs.rs/windows-sys/0.59.0/windows_sys/

import ctypes
import re
from enum import IntEnum, unique
from typing import NewType, Protocol

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
)

################################################################################
# Drive names
################################################################################

# Match a drive letter, with or without the colon, a trailing backslash, or the
# `\\.\` device prefix Windows uses for raw drives.
_DRIVE_NAME = re.compile(r"^(?:\\\\\.\\)?([A-Za-z]):?\\?$")


def normalize_name(name: str) -> str:
    r"""Turn `D`, `D:`, `D:\`, `d:` or `\\.\D:` into `D:`."""
    stripped = name.strip()
    match = _DRIVE_NAME.match(stripped)
    if match is None:
        shown = stripped or "an empty name"
        raise ValueError(f"{shown} isn't a drive letter such as D:")
    return f"{match.group(1).upper()}:"


def root_path(drive_name: str) -> str:
    r"""Return the drive's root directory, `D:\`, as GetDriveTypeW takes it."""
    return f"{drive_name}\\"


def device_path(drive_name: str) -> str:
    r"""Return the path to the drive itself, `\\.\D:`, not a file on it."""
    return f"\\\\.\\{drive_name}"


################################################################################
# Drive types
################################################################################


# Values from Microsoft's page for GetDriveTypeW:
# https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-getdrivetypew
@unique
class DriveType(IntEnum):
    """What kind of drive a letter is, as Windows reports it."""

    UNKNOWN = 0
    NO_ROOT_DIR = 1
    REMOVABLE = 2
    FIXED = 3
    REMOTE = 4
    CDROM = 5
    RAMDISK = 6


# What each drive type means, in plain words. Microsoft counts some flash drives
# as fixed, so a fixed drive is "such as" a hard disk.
_DRIVE_TYPE_MEANINGS: dict[int, str] = {
    DriveType.UNKNOWN: "unknown type",
    DriveType.NO_ROOT_DIR: "nothing at that letter",
    DriveType.REMOVABLE: "removable drive, such as a USB stick",
    DriveType.FIXED: "fixed drive, such as a hard disk",
    DriveType.REMOTE: "network drive",
    DriveType.CDROM: "optical drive",
    DriveType.RAMDISK: "RAM disk",
}


def drive_type_reason(drive_type: int) -> DriveConnectReason:
    """Return why a drive of this type, which isn't optical, can't be used."""
    if drive_type == DriveType.NO_ROOT_DIR:
        return DriveConnectReason.NO_SUCH_DRIVE
    return DriveConnectReason.NOT_OPTICAL


def drive_type_report(drive_type: int) -> str:
    """Return a drive type and its meaning, as `DriveConnectError` shows it.

    For example "Windows drive type 3: fixed drive, such as a hard disk".
    """
    meaning = _DRIVE_TYPE_MEANINGS.get(drive_type, "unrecognized")
    return f"Windows drive type {drive_type}: {meaning}"


################################################################################
# Error codes
################################################################################


# Values from Microsoft's lists of system error codes:
# https://learn.microsoft.com/windows/win32/debug/system-error-codes--0-499-
# https://learn.microsoft.com/windows/win32/debug/system-error-codes--1000-1299-
@unique
class ErrorCode(IntEnum):
    """A Windows error code that Disc Badger tells apart from the others."""

    INVALID_FUNCTION = 1
    FILE_NOT_FOUND = 2
    PATH_NOT_FOUND = 3
    ACCESS_DENIED = 5
    INVALID_HANDLE = 6
    NOT_READY = 21
    NOT_SUPPORTED = 50
    DEV_NOT_EXIST = 55
    INVALID_PARAMETER = 87
    SEM_TIMEOUT = 121
    IO_DEVICE = 1117
    DEVICE_NOT_CONNECTED = 1167


# What each Windows error code from sending a command means. Any other code is
# unrecognized.
_OS_FAILURE_KINDS: dict[int, OsFailureKind] = {
    ErrorCode.SEM_TIMEOUT: OsFailureKind.TIMEOUT,
    ErrorCode.ACCESS_DENIED: OsFailureKind.DENIED,
    ErrorCode.FILE_NOT_FOUND: OsFailureKind.GONE,
    ErrorCode.PATH_NOT_FOUND: OsFailureKind.GONE,
    ErrorCode.INVALID_HANDLE: OsFailureKind.GONE,
    ErrorCode.DEV_NOT_EXIST: OsFailureKind.GONE,
    ErrorCode.DEVICE_NOT_CONNECTED: OsFailureKind.GONE,
    ErrorCode.NOT_READY: OsFailureKind.NO_MEDIUM,  # how Windows reports no disc
    ErrorCode.NOT_SUPPORTED: OsFailureKind.INVALID,
    ErrorCode.INVALID_PARAMETER: OsFailureKind.INVALID,
    ErrorCode.IO_DEVICE: OsFailureKind.TRANSPORT,
}


def os_error_report(os_error: int) -> str:
    """Return what a Windows error code is, such as "Windows error 121"."""
    return f"Windows error {os_error}"


def os_failure_kind(os_error: int) -> OsFailureKind:
    """Return what a Windows error code from sending a command means."""
    return _OS_FAILURE_KINDS.get(os_error, OsFailureKind.UNRECOGNIZED)


def connect_reason(os_error: int) -> DriveConnectReason:
    """Translate a Windows error code from connecting to a drive."""
    if os_error in (ErrorCode.FILE_NOT_FOUND, ErrorCode.PATH_NOT_FOUND):
        return DriveConnectReason.NO_SUCH_DRIVE
    if os_error == ErrorCode.INVALID_FUNCTION:
        return DriveConnectReason.REFUSED
    if os_error == ErrorCode.ACCESS_DENIED:
        return DriveConnectReason.DENIED
    return DriveConnectReason.UNRECOGNIZED


################################################################################
# Pass-through structures
################################################################################

# Room for the drive's sense data: its report of an error or other condition. In
# fixed format, its fields take the first 18 bytes, and a drive may add more, up
# to 252 in all (SPC-3 section 4.5.3). Room for all 252 means none is ever cut
# off.
SENSE_DATA_SIZE_BYTES = 252

# The structures below follow the 64-bit C headers, and a test checks their
# layout. Disc Badger runs only on 64-bit Python; `system` refuses any other.


class ScsiPassThroughDirect(ctypes.Structure):
    """Windows SCSI_PASS_THROUGH_DIRECT, field for field, from ntddscsi.h.

    "Direct": the drive reads and writes the caller's data buffer itself, rather
    than through a copy Windows makes.
    """

    # C starts each field at a multiple of its own size, and makes the
    # structure's size a multiple of its largest field's, adding padding where
    # needed; ctypes does the same. The comments below mark the padding.

    _fields_ = (
        ("Length", ctypes.c_uint16),
        ("ScsiStatus", ctypes.c_uint8),
        ("PathId", ctypes.c_uint8),
        ("TargetId", ctypes.c_uint8),
        ("Lun", ctypes.c_uint8),
        ("CdbLength", ctypes.c_uint8),
        ("SenseInfoLength", ctypes.c_uint8),
        ("DataIn", ctypes.c_uint8),
        # Padding: 3 bytes, so the next field starts at a multiple of 4 (12).
        ("DataTransferLength", ctypes.c_uint32),
        ("TimeOutValue", ctypes.c_uint32),
        # Padding: 4 bytes, so the next field starts at a multiple of 8 (24).
        ("DataBuffer", ctypes.c_void_p),
        ("SenseInfoOffset", ctypes.c_uint32),
        ("Cdb", ctypes.c_uint8 * 16),
        # Padding: 4 bytes, to make the size a multiple of 8 (56).
    )


class ScsiPassThroughBuffer(ctypes.Structure):
    """The buffer handed to Windows for one command.

    It holds `ScsiPassThroughDirect`, then room for the drive's sense data.
    """

    # Windows writes the sense data SenseInfoOffset bytes from the start of the
    # buffer, so it has to live in the same block of memory.

    _fields_ = (
        ("pass_through", ScsiPassThroughDirect),
        # Matches Microsoft's sample structure, so Sense starts at 60.
        ("Filler", ctypes.c_uint32),
        ("Sense", ctypes.c_uint8 * SENSE_DATA_SIZE_BYTES),
        # Padding: none, since the size is already a multiple of 8 (312).
    )


################################################################################
# Sending a command
################################################################################

# The control code that asks Windows to pass a SCSI command straight to the
# drive, with the drive reading and writing the data buffer directly. ntddscsi.h
# builds it with CTL_CODE::
#
#     CTL_CODE(FILE_DEVICE_CONTROLLER, 0x405, METHOD_BUFFERED,
#              FILE_READ_ACCESS | FILE_WRITE_ACCESS)
#     = (4 << 16) | ((1 | 2) << 14) | (0x405 << 2) | 0
#     = 0x4D014
IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x4D014
# Direction of the data a command moves; eject moves none. From ntddscsi.h.
SCSI_IOCTL_DATA_UNSPECIFIED = 2


def pass_through_buffer_for(command: DriveCommand) -> ScsiPassThroughBuffer:
    """Return the buffer that sends `command`, which moves no data."""
    cdb = command.cdb
    pass_through_buffer = ScsiPassThroughBuffer()
    pass_through = pass_through_buffer.pass_through
    pass_through.Length = ctypes.sizeof(ScsiPassThroughDirect)
    pass_through.CdbLength = len(cdb)
    pass_through.SenseInfoLength = SENSE_DATA_SIZE_BYTES
    pass_through.SenseInfoOffset = ScsiPassThroughBuffer.Sense.offset
    pass_through.DataIn = SCSI_IOCTL_DATA_UNSPECIFIED
    pass_through.TimeOutValue = command.timeout_s
    pass_through.Cdb[: len(cdb)] = list(cdb)
    return pass_through_buffer


def command_result(
    pass_through_buffer: ScsiPassThroughBuffer,
    os_error: int | None,
) -> CommandResult:
    """Return what came back from sending `pass_through_buffer`.

    `os_error` is Windows' error code when it couldn't deliver the command,
    otherwise None.
    """
    # Report a failed call as an OS error. A command the drive rejected is still
    # delivered, with a bad status.
    if os_error is not None:
        return OsFailure(
            kind=os_failure_kind(os_error),
            os_error=os_error,
            os_report=os_error_report(os_error),
        )
    return DriveAnswer(
        scsi_status=pass_through_buffer.pass_through.ScsiStatus,
        sense_data=SenseData.parse(bytes(pass_through_buffer.Sense)),
    )


################################################################################
# The transport
################################################################################

# For connecting to a drive.
GENERIC_READ_WRITE = 0x80000000 | 0x40000000  # GENERIC_READ | GENERIC_WRITE
FILE_SHARE_READ_WRITE = 1 | 2  # FILE_SHARE_READ | FILE_SHARE_WRITE
OPEN_EXISTING = 3

Handle = NewType("Handle", int)
"""A Windows handle: the number naming a file or device a program is using.

Windows gives one when a program asks for access to something, here a drive, for
the program to name it in later calls. In C it's pointer-sized (HANDLE), but
only Windows knows what it refers to; ctypes gives it to Python as an int.
"""


class TransportWindowsC(Protocol):
    """The calls into Windows that `TransportWindows` makes.

    `transport_windows_c` follows it on Windows; tests use a fake.
    """

    def get_drive_type(self, root_path_name: str) -> int:
        """Return what kind of drive a root directory is on."""
        ...

    def create_file(
        self,
        file_name: str,
        desired_access: int,
        share_mode: int,
        creation_disposition: int,
    ) -> Handle | None:
        """Return a handle to a file or device, or None if Windows refused."""
        ...

    def device_io_control(
        self,
        device_handle: Handle,
        io_control_code: int,
        in_out_buffer: ScsiPassThroughBuffer,
    ) -> bool:
        """Send a buffer to a device; return whether Windows delivered it."""
        ...

    def close_handle(self, device_handle: Handle) -> bool:
        """Close a handle; return whether Windows closed it."""
        ...

    def last_error(self) -> int:
        """Return Windows' error code for the last call."""
        ...


class TransportWindows(Transport):
    """One optical drive connected for SCSI pass-through, e.g. `D:`."""

    def __init__(
        self,
        drive_name: str,
        c_calls: TransportWindowsC,
    ) -> None:
        """Connect to a drive through `c_calls`, or raise DriveConnectError."""
        # The name goes into a device path given write access, so accept only a
        # normalized drive letter, which is all Drive.connect passes; anything
        # else is a bug in the caller.
        if normalize_name(drive_name) != drive_name:
            message = f"{drive_name!r} isn't a normalized drive name such as D:"
            raise ValueError(message)
        self.drive_name = drive_name
        self._c_calls = c_calls
        # Ask Windows what kind of drive the letter is, and refuse all but an
        # optical drive, so a hard disk or USB stick never even gets a handle.
        drive_type = c_calls.get_drive_type(root_path(drive_name))
        if drive_type != DriveType.CDROM:
            raise DriveConnectError(
                drive_name=drive_name,
                os_error=None,
                os_report=drive_type_report(drive_type),
                reason=drive_type_reason(drive_type),
            )
        # Get a handle to the drive itself, for reading and writing, as
        # pass-through needs. Share it: an exclusive handle can't be had while
        # another program, such as Windows Explorer, has a handle to the drive.
        device_handle = c_calls.create_file(
            file_name=device_path(drive_name),
            desired_access=GENERIC_READ_WRITE,
            share_mode=FILE_SHARE_READ_WRITE,
            creation_disposition=OPEN_EXISTING,
        )
        if device_handle is None:
            os_error = c_calls.last_error()
            raise DriveConnectError(
                drive_name=drive_name,
                os_error=os_error,
                os_report=os_error_report(os_error),
                reason=connect_reason(os_error),
            )
        self._device_handle: Handle | None = device_handle

    def disconnect(self) -> None:
        """Give up the handle; calling it again does nothing."""
        # Windows reuses handle numbers, so closing one twice could close
        # another program's handle.
        if self._device_handle is None:
            return
        # CloseHandle's result is ignored: if it fails there is nothing more to
        # do, and the handle is given up either way.
        _ = self._c_calls.close_handle(self._device_handle)
        self._device_handle = None

    def send(self, command: DriveCommand) -> CommandResult:
        """Send one command that moves no data."""
        if self._device_handle is None:
            raise RuntimeError(f"{self.drive_name} is disconnected")
        # Send the buffer and get it back: Windows fills in ScsiStatus and Sense
        # when the drive answers.
        pass_through_buffer = pass_through_buffer_for(command)
        delivered = self._c_calls.device_io_control(
            device_handle=self._device_handle,
            io_control_code=IOCTL_SCSI_PASS_THROUGH_DIRECT,
            in_out_buffer=pass_through_buffer,
        )
        # Windows' error code means something only when the call failed.
        os_error = None if delivered else self._c_calls.last_error()
        return command_result(
            pass_through_buffer=pass_through_buffer,
            os_error=os_error,
        )
