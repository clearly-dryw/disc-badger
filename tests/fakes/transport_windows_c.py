# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for `transport_windows_c`, the calls into Windows."""

from dataclasses import dataclass

from disc_badger.drive.scsi_status import ScsiStatus
from disc_badger.drive.transport.transport_windows import (
    DriveType,
    Handle,
    ScsiPassThroughBuffer,
)

DEVICE_HANDLE = Handle(1234)  # any number: the fake only passes it back

# A Windows error code the transport doesn't name, since it treats it like any
# other it doesn't know, for tests to have the fake answer with. From
# Microsoft's lists of system error codes, which `transport_windows` links.
ERROR_GEN_FAILURE = 31  # "A device attached to the system is not functioning."


@dataclass(frozen=True)
class WindowsAnswer:
    """What Windows writes into a delivered command's buffer from the drive."""

    scsi_status: int = ScsiStatus.GOOD
    sense_data: bytes = b""


class TransportWindowsCFake:
    """Stands in for `transport_windows_c`: records calls, answers as set.

    `device_handle` None makes connecting fail, and `windows_answer` None makes
    sending fail, each with `os_error`.
    """

    def __init__(
        self,
        *,
        drive_type: int = DriveType.CDROM,
        device_handle: Handle | None = DEVICE_HANDLE,
        windows_answer: WindowsAnswer | None = WindowsAnswer(),
        os_error: int = 0,
    ) -> None:
        self.drive_type = drive_type
        self.device_handle = device_handle
        self.windows_answer = windows_answer
        self.os_error = os_error
        self.calls: list[tuple[object, ...]] = []

    def get_drive_type(self, root_path_name: str) -> int:
        self.calls.append(("get_drive_type", root_path_name))
        return self.drive_type

    def create_file(
        self,
        file_name: str,
        desired_access: int,
        share_mode: int,
        creation_disposition: int,
    ) -> Handle | None:
        self.calls.append(
            (
                "create_file",
                file_name,
                desired_access,
                share_mode,
                creation_disposition,
            ),
        )
        return self.device_handle

    def device_io_control(
        self,
        device_handle: Handle,
        io_control_code: int,
        in_out_buffer: ScsiPassThroughBuffer,
    ) -> bool:
        pass_through = in_out_buffer.pass_through
        cdb = bytes(pass_through.Cdb)[: pass_through.CdbLength]
        self.calls.append(
            ("device_io_control", device_handle, io_control_code, cdb),
        )
        answer = self.windows_answer
        if answer is None:
            return False
        pass_through.ScsiStatus = answer.scsi_status
        in_out_buffer.Sense[: len(answer.sense_data)] = list(answer.sense_data)
        return True

    def close_handle(self, device_handle: Handle) -> bool:
        self.calls.append(("close_handle", device_handle))
        return True

    def last_error(self) -> int:
        return self.os_error
