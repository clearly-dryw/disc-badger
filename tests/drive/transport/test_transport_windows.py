# SPDX-License-Identifier: GPL-3.0-or-later
"""The Windows transport and what it builds on, checked on any OS."""

import ctypes

import pytest

from disc_badger.drive.commands import EJECT
from disc_badger.drive.scsi_status import ScsiStatus
from disc_badger.drive.sense_data import SenseData
from disc_badger.drive.transport import (
    DriveAnswer,
    DriveConnectError,
    DriveConnectReason,
    OsFailure,
    OsFailureKind,
)
from disc_badger.drive.transport.transport_windows import (
    FILE_SHARE_READ_WRITE,
    GENERIC_READ_WRITE,
    IOCTL_SCSI_PASS_THROUGH_DIRECT,
    OPEN_EXISTING,
    SCSI_IOCTL_DATA_UNSPECIFIED,
    SENSE_DATA_SIZE_BYTES,
    DriveType,
    ErrorCode,
    ScsiPassThroughBuffer,
    ScsiPassThroughDirect,
    TransportWindows,
    command_result,
    connect_reason,
    device_path,
    drive_type_reason,
    drive_type_report,
    normalize_name,
    os_failure_kind,
    pass_through_buffer_for,
    root_path,
)
from tests.fakes import (
    DEVICE_HANDLE,
    ERROR_GEN_FAILURE,
    SENSE_DATA_TRAY_LOCKED_DESCRIPTOR,
    SENSE_DATA_TRAY_LOCKED_FIXED,
    TransportWindowsCFake,
    WindowsAnswer,
)

# The layout the 64-bit C headers give, padding included. It's written out
# rather than computed, so the tests compare ctypes with the headers, not with
# itself.
PASS_THROUGH_SIZE_BYTES = 56  # ScsiPassThroughDirect
SENSE_OFFSET_BYTES = 60  # where Sense starts in ScsiPassThroughBuffer
PASS_THROUGH_BUFFER_SIZE_BYTES = 312  # ScsiPassThroughBuffer

# A drive type Microsoft's page doesn't list, as a later Windows might add.
DRIVE_TYPE_NOT_LISTED = 7


@pytest.mark.parametrize("name", ["D", "D:", "D:\\", "d:", "\\\\.\\D:", " D: "])
def test_drive_names(name: str) -> None:
    assert normalize_name(name) == "D:"


@pytest.mark.parametrize("name", ["", "DF", "1:", "D:\\Videos", "/dev/sr0"])
def test_not_a_drive_name(name: str) -> None:
    with pytest.raises(ValueError, match="isn't a drive letter"):
        # It raises, so there is no result to use.
        _ = normalize_name(name)


@pytest.mark.parametrize("name", ["", "  "])
def test_an_empty_name_says_so(name: str) -> None:
    with pytest.raises(ValueError, match=r"^an empty name isn't a drive"):
        # It raises, so there is no result to use.
        _ = normalize_name(name)


def test_each_function_gets_the_form_of_name_it_takes() -> None:
    assert root_path("D:") == "D:\\"  # a volume's root directory
    assert device_path("D:") == "\\\\.\\D:"  # the drive itself


def test_structure_layout_matches_windows() -> None:
    """TC-DRIVE-001: sizes and the sense offset."""
    assert ctypes.sizeof(ScsiPassThroughDirect) == PASS_THROUGH_SIZE_BYTES
    assert ScsiPassThroughBuffer.Sense.offset == SENSE_OFFSET_BYTES
    buffer_size_bytes = ctypes.sizeof(ScsiPassThroughBuffer)
    assert buffer_size_bytes == PASS_THROUGH_BUFFER_SIZE_BYTES


# Where each field starts, from the 64-bit C headers. Checking every one catches
# two fields of the same size swapped, which the sizes alone can't.
@pytest.mark.parametrize(
    ("field", "offset_bytes"),
    [
        ("Length", 0),
        ("ScsiStatus", 2),
        ("PathId", 3),
        ("TargetId", 4),
        ("Lun", 5),
        ("CdbLength", 6),
        ("SenseInfoLength", 7),
        ("DataIn", 8),
        ("DataTransferLength", 12),
        ("TimeOutValue", 16),
        ("DataBuffer", 24),
        ("SenseInfoOffset", 32),
        ("Cdb", 36),
    ],
)
def test_each_pass_through_field_is_where_windows_reads_it(
    field: str,
    offset_bytes: int,
) -> None:
    assert getattr(ScsiPassThroughDirect, field).offset == offset_bytes


def test_the_filler_puts_sense_data_where_windows_expects_it() -> None:
    assert ScsiPassThroughBuffer.Filler.offset == PASS_THROUGH_SIZE_BYTES


# The values are written out from Microsoft's documentation and the SDK headers
# (`transport_windows` links them) rather than imported, so a wrong value in the
# module can't pass unnoticed. The other tests then use the names.
def test_windows_values_match_the_documentation() -> None:
    constants = {
        "IOCTL_SCSI_PASS_THROUGH_DIRECT": IOCTL_SCSI_PASS_THROUGH_DIRECT,
        "SCSI_IOCTL_DATA_UNSPECIFIED": SCSI_IOCTL_DATA_UNSPECIFIED,
        "GENERIC_READ_WRITE": GENERIC_READ_WRITE,
        "FILE_SHARE_READ_WRITE": FILE_SHARE_READ_WRITE,
        "OPEN_EXISTING": OPEN_EXISTING,
        "SENSE_DATA_SIZE_BYTES": SENSE_DATA_SIZE_BYTES,
    }
    assert constants == {
        "IOCTL_SCSI_PASS_THROUGH_DIRECT": 0x4D014,
        "SCSI_IOCTL_DATA_UNSPECIFIED": 2,
        "GENERIC_READ_WRITE": 0xC0000000,
        "FILE_SHARE_READ_WRITE": 3,
        "OPEN_EXISTING": 3,
        "SENSE_DATA_SIZE_BYTES": 252,  # the most SPC-3 section 4.5.3 allows
    }
    assert {member.name: member.value for member in DriveType} == {
        "UNKNOWN": 0,
        "NO_ROOT_DIR": 1,
        "REMOVABLE": 2,
        "FIXED": 3,
        "REMOTE": 4,
        "CDROM": 5,
        "RAMDISK": 6,
    }
    assert {member.name: member.value for member in ErrorCode} == {
        "INVALID_FUNCTION": 1,
        "FILE_NOT_FOUND": 2,
        "PATH_NOT_FOUND": 3,
        "ACCESS_DENIED": 5,
        "INVALID_HANDLE": 6,
        "NOT_READY": 21,
        "NOT_SUPPORTED": 50,
        "DEV_NOT_EXIST": 55,
        "INVALID_PARAMETER": 87,
        "SEM_TIMEOUT": 121,
        "IO_DEVICE": 1117,
        "DEVICE_NOT_CONNECTED": 1167,
    }


def test_the_pass_through_buffer_carries_the_command() -> None:
    pass_through = pass_through_buffer_for(EJECT).pass_through
    assert pass_through.Length == PASS_THROUGH_SIZE_BYTES
    assert pass_through.CdbLength == len(EJECT.cdb)
    assert pass_through.SenseInfoLength == SENSE_DATA_SIZE_BYTES
    assert pass_through.SenseInfoOffset == SENSE_OFFSET_BYTES
    assert pass_through.DataIn == SCSI_IOCTL_DATA_UNSPECIFIED
    assert pass_through.DataTransferLength == 0  # eject moves no data
    assert pass_through.DataBuffer is None
    assert pass_through.TimeOutValue == EJECT.timeout_s
    padding = bytes(len(pass_through.Cdb) - len(EJECT.cdb))
    assert bytes(pass_through.Cdb) == EJECT.cdb + padding


def test_a_delivered_command_returns_the_drives_answer() -> None:
    pass_through_buffer = pass_through_buffer_for(EJECT)
    # Answer as a drive refusing the command would.
    pass_through_buffer.pass_through.ScsiStatus = ScsiStatus.CHECK_CONDITION
    sense_sent = SENSE_DATA_TRAY_LOCKED_FIXED
    pass_through_buffer.Sense[: len(sense_sent)] = list(sense_sent)
    answer = command_result(pass_through_buffer, os_error=None)
    assert answer == DriveAnswer(
        scsi_status=ScsiStatus.CHECK_CONDITION,
        sense_data=SenseData(
            raw=sense_sent,  # what the drive sent, not the whole buffer
            deferred=False,
            sense_key=0x5,  # ILLEGAL REQUEST
            asc=0x53,  # MEDIUM REMOVAL PREVENTED, with the ASCQ
            ascq=0x02,
        ),
    )


def test_an_undelivered_command_returns_the_os_error() -> None:
    answer = command_result(
        pass_through_buffer_for(EJECT),
        os_error=ErrorCode.SEM_TIMEOUT,  # the drive stopped answering
    )
    assert answer == OsFailure(
        kind=OsFailureKind.TIMEOUT,
        os_error=ErrorCode.SEM_TIMEOUT,
        # Written out, so a wrong format or number can't pass unnoticed.
        os_report="Windows error 121",
    )


@pytest.mark.parametrize(
    ("os_error", "kind"),
    [
        (ErrorCode.SEM_TIMEOUT, OsFailureKind.TIMEOUT),
        (ErrorCode.ACCESS_DENIED, OsFailureKind.DENIED),
        (ErrorCode.FILE_NOT_FOUND, OsFailureKind.GONE),
        (ErrorCode.PATH_NOT_FOUND, OsFailureKind.GONE),
        (ErrorCode.INVALID_HANDLE, OsFailureKind.GONE),
        (ErrorCode.DEV_NOT_EXIST, OsFailureKind.GONE),
        (ErrorCode.DEVICE_NOT_CONNECTED, OsFailureKind.GONE),
        (ErrorCode.NOT_READY, OsFailureKind.NO_MEDIUM),
        (ErrorCode.NOT_SUPPORTED, OsFailureKind.INVALID),
        (ErrorCode.INVALID_PARAMETER, OsFailureKind.INVALID),
        (ErrorCode.IO_DEVICE, OsFailureKind.TRANSPORT),
        (ERROR_GEN_FAILURE, OsFailureKind.UNRECOGNIZED),
        (ErrorCode.INVALID_FUNCTION, OsFailureKind.UNRECOGNIZED),  # any other
    ],
)
def test_os_failure_kinds(
    os_error: int,
    kind: OsFailureKind,
) -> None:
    assert os_failure_kind(os_error) is kind


@pytest.mark.parametrize(
    ("drive_type", "reason"),
    [
        (DriveType.NO_ROOT_DIR, DriveConnectReason.NO_SUCH_DRIVE),
        (DriveType.FIXED, DriveConnectReason.NOT_OPTICAL),
        (DriveType.REMOVABLE, DriveConnectReason.NOT_OPTICAL),
        (DriveType.REMOTE, DriveConnectReason.NOT_OPTICAL),
        (DriveType.UNKNOWN, DriveConnectReason.NOT_OPTICAL),
        (DriveType.RAMDISK, DriveConnectReason.NOT_OPTICAL),
        (DRIVE_TYPE_NOT_LISTED, DriveConnectReason.NOT_OPTICAL),
    ],
)
def test_drive_type_reasons(
    drive_type: int,
    reason: DriveConnectReason,
) -> None:
    assert drive_type_reason(drive_type) is reason


# Written out, so a wrong format or number can't pass unnoticed.
@pytest.mark.parametrize(
    ("drive_type", "report"),
    [
        (DriveType.UNKNOWN, "Windows drive type 0: unknown type"),
        (DriveType.NO_ROOT_DIR, "Windows drive type 1: nothing at that letter"),
        (
            DriveType.REMOVABLE,
            "Windows drive type 2: removable drive, such as a USB stick",
        ),
        (
            DriveType.FIXED,
            "Windows drive type 3: fixed drive, such as a hard disk",
        ),
        (DriveType.REMOTE, "Windows drive type 4: network drive"),
        (DriveType.CDROM, "Windows drive type 5: optical drive"),
        (DriveType.RAMDISK, "Windows drive type 6: RAM disk"),
        (DRIVE_TYPE_NOT_LISTED, "Windows drive type 7: unrecognized"),
    ],
)
def test_drive_type_reports(
    drive_type: int,
    report: str,
) -> None:
    assert drive_type_report(drive_type) == report


@pytest.mark.parametrize(
    ("os_error", "reason"),
    [
        (ErrorCode.FILE_NOT_FOUND, DriveConnectReason.NO_SUCH_DRIVE),
        (ErrorCode.PATH_NOT_FOUND, DriveConnectReason.NO_SUCH_DRIVE),
        (ErrorCode.INVALID_FUNCTION, DriveConnectReason.REFUSED),
        (ErrorCode.ACCESS_DENIED, DriveConnectReason.DENIED),
        (ERROR_GEN_FAILURE, DriveConnectReason.UNRECOGNIZED),  # any other
    ],
)
def test_connect_reasons(
    os_error: int,
    reason: DriveConnectReason,
) -> None:
    assert connect_reason(os_error) is reason


def test_connect_gets_a_shared_read_write_handle() -> None:
    c_calls = TransportWindowsCFake()
    _ = TransportWindows(drive_name="D:", c_calls=c_calls)
    assert c_calls.calls == [
        ("get_drive_type", "D:\\"),
        (
            "create_file",
            "\\\\.\\D:",
            GENERIC_READ_WRITE,
            FILE_SHARE_READ_WRITE,
            OPEN_EXISTING,
        ),
    ]


@pytest.mark.parametrize(
    ("drive_type", "reason"),
    [
        (DriveType.NO_ROOT_DIR, DriveConnectReason.NO_SUCH_DRIVE),
        (DriveType.FIXED, DriveConnectReason.NOT_OPTICAL),
    ],
)
def test_a_drive_that_isnt_optical_never_gets_a_handle(
    drive_type: int,
    reason: DriveConnectReason,
) -> None:
    c_calls = TransportWindowsCFake(drive_type=drive_type)
    with pytest.raises(DriveConnectError) as error_info:
        # It raises, so there is no result to use.
        _ = TransportWindows(drive_name="C:", c_calls=c_calls)
    assert error_info.value.reason is reason
    assert error_info.value.os_error is None
    assert error_info.value.os_report == drive_type_report(drive_type)
    assert c_calls.calls == [("get_drive_type", "C:\\")]


def test_a_refused_connection_says_why() -> None:
    c_calls = TransportWindowsCFake(
        device_handle=None,
        os_error=ErrorCode.INVALID_FUNCTION,
    )
    with pytest.raises(DriveConnectError) as error_info:
        # It raises, so there is no result to use.
        _ = TransportWindows(drive_name="D:", c_calls=c_calls)
    assert error_info.value.reason is DriveConnectReason.REFUSED
    assert error_info.value.os_error == ErrorCode.INVALID_FUNCTION
    # Written out, so a wrong format or number can't pass unnoticed.
    assert error_info.value.os_report == "Windows error 1"


def test_connect_needs_a_normalized_name() -> None:
    c_calls = TransportWindowsCFake()
    with pytest.raises(ValueError, match="isn't a normalized drive name"):
        # It raises, so there is no result to use.
        _ = TransportWindows(drive_name="d", c_calls=c_calls)
    assert c_calls.calls == []


def test_send_passes_the_command_and_returns_the_answer() -> None:
    c_calls = TransportWindowsCFake()
    transport = TransportWindows(drive_name="D:", c_calls=c_calls)
    answer = transport.send(EJECT)
    assert c_calls.calls[-1] == (
        "device_io_control",
        DEVICE_HANDLE,
        IOCTL_SCSI_PASS_THROUGH_DIRECT,
        EJECT.cdb,
    )
    assert answer == DriveAnswer(scsi_status=ScsiStatus.GOOD, sense_data=None)


@pytest.mark.parametrize(
    "sense_sent",
    [SENSE_DATA_TRAY_LOCKED_FIXED, SENSE_DATA_TRAY_LOCKED_DESCRIPTOR],
    ids=["fixed format", "descriptor format"],
)
def test_send_returns_a_refusal_and_its_sense_data(sense_sent: bytes) -> None:
    c_calls = TransportWindowsCFake(
        windows_answer=WindowsAnswer(
            scsi_status=ScsiStatus.CHECK_CONDITION,
            sense_data=sense_sent,
        ),
    )
    transport = TransportWindows(drive_name="D:", c_calls=c_calls)
    answer = transport.send(EJECT)
    assert answer == DriveAnswer(
        scsi_status=ScsiStatus.CHECK_CONDITION,
        sense_data=SenseData(
            raw=sense_sent,
            deferred=False,
            sense_key=0x5,  # ILLEGAL REQUEST
            asc=0x53,  # MEDIUM REMOVAL PREVENTED, with the ASCQ
            ascq=0x02,
        ),
    )


def test_send_reports_an_undelivered_command() -> None:
    c_calls = TransportWindowsCFake(
        windows_answer=None,
        os_error=ErrorCode.SEM_TIMEOUT,
    )
    transport = TransportWindows(drive_name="D:", c_calls=c_calls)
    answer = transport.send(EJECT)
    assert isinstance(answer, OsFailure)
    assert answer.os_error == ErrorCode.SEM_TIMEOUT
    assert answer.kind is OsFailureKind.TIMEOUT


def test_disconnect_closes_the_handle_once() -> None:
    c_calls = TransportWindowsCFake()
    transport = TransportWindows(drive_name="D:", c_calls=c_calls)
    transport.disconnect()
    transport.disconnect()
    assert c_calls.calls.count(("close_handle", DEVICE_HANDLE)) == 1
    with pytest.raises(RuntimeError, match="disconnected"):
        # It raises, so there is no result to use.
        _ = transport.send(EJECT)
