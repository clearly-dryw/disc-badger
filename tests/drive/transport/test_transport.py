# SPDX-License-Identifier: GPL-3.0-or-later
"""What a transport reports and raises, in plain words."""

import pytest

from disc_badger.drive.scsi_status import ScsiStatus
from disc_badger.drive.sense_data import ResponseCode, SenseData
from disc_badger.drive.transport import (
    DriveAnswer,
    DriveConnectError,
    DriveConnectReason,
)
from tests.fakes import GOOD, OS_FAILED, REFUSED, SENSE_DATA_TRAY_LOCKED_FIXED

# The expected messages below are written out, so a wrong format or number can't
# pass unnoticed.


def test_a_good_answer_succeeded() -> None:
    assert GOOD.succeeded()


def test_a_failure_did_not_succeed() -> None:
    assert not REFUSED.succeeded()
    assert not OS_FAILED.succeeded()


def test_a_good_answer_has_no_failure_reason() -> None:
    with pytest.raises(ValueError, match="no failure reason"):
        # It raises, so there is no result to use.
        _ = GOOD.failure_reason()


def test_an_os_failure_gives_its_report_then_its_meaning() -> None:
    assert OS_FAILED.failure_reason() == (
        "Windows error 121: the drive didn't answer in time"
    )


def test_a_refusal_gives_its_sense_code_then_its_meaning() -> None:
    assert REFUSED.failure_reason() == (
        "sense 5/53/02: the drive rejected the request"
    )


@pytest.mark.parametrize(
    "sense_data",
    [None, SenseData.parse(bytes([0x7F, 1, 2, 3]))],  # none, or vendor format
)
def test_a_refusal_without_a_sense_key_gives_its_status(
    sense_data: SenseData | None,
) -> None:
    refused = DriveAnswer(
        scsi_status=ScsiStatus.CHECK_CONDITION,
        sense_data=sense_data,
    )
    assert refused.failure_reason() == (
        "SCSI status 0x02: the drive didn't say why"
    )


def test_another_status_gives_its_report_then_its_meaning() -> None:
    busy = DriveAnswer(scsi_status=ScsiStatus.BUSY, sense_data=None)
    assert busy.failure_reason() == "SCSI status 0x08: the drive was busy"


def test_only_check_condition_reads_the_sense_data() -> None:
    busy = DriveAnswer(
        scsi_status=ScsiStatus.BUSY,
        sense_data=REFUSED.sense_data,
    )
    assert busy.failure_reason() == "SCSI status 0x08: the drive was busy"


def test_a_deferred_error_says_so() -> None:
    deferred_sent = bytes([ResponseCode.DEFERRED_FIXED])
    deferred_sent += SENSE_DATA_TRAY_LOCKED_FIXED[1:]
    refused_earlier = DriveAnswer(
        scsi_status=ScsiStatus.CHECK_CONDITION,
        sense_data=SenseData.parse(deferred_sent),
    )
    assert refused_earlier.failure_reason() == (
        "deferred sense 5/53/02: the drive rejected the request"
    )


def test_a_connect_error_gives_an_error_code_then_its_reason() -> None:
    refused = DriveConnectError(
        drive_name="D:",
        os_error=1,
        os_report="Windows error 1",
        reason=DriveConnectReason.REFUSED,
    )
    assert refused.failure_reason() == "Windows error 1: refused"
    assert str(refused) == "couldn't connect to D: (Windows error 1: refused)"


def test_a_connect_error_gives_a_report_that_says_its_own_meaning() -> None:
    hard_disk = DriveConnectError(
        drive_name="C:",
        os_error=None,
        os_report="Windows drive type 3: fixed drive, such as a hard disk",
        reason=DriveConnectReason.NOT_OPTICAL,
    )
    assert hard_disk.failure_reason() == (
        "Windows drive type 3: fixed drive, such as a hard disk"
    )


def test_a_connect_error_with_no_report_gives_its_reason() -> None:
    not_optical = DriveConnectError(
        drive_name="C:",
        os_error=None,
        os_report=None,
        reason=DriveConnectReason.NOT_OPTICAL,
    )
    assert str(not_optical) == "couldn't connect to C: (not an optical drive)"


def test_an_os_error_needs_a_report() -> None:
    with pytest.raises(ValueError, match="an os_error needs an os_report"):
        # It raises, so there is no result to use.
        _ = DriveConnectError(
            drive_name="D:",
            os_error=1,
            os_report=None,
            reason=DriveConnectReason.REFUSED,
        )
