# SPDX-License-Identifier: GPL-3.0-or-later
"""SCSI status: what each status means, in plain words."""

import pytest

from disc_badger.drive.scsi_status import ScsiStatus, scsi_status_meaning

# A status T10's list doesn't have; 22h was COMMAND TERMINATED, now obsolete.
SCSI_STATUS_NOT_LISTED = 0x22


# The values are written out from T10's list rather than read from the module,
# so a wrong one can't pass unnoticed.
def test_the_values_match_t10s_list() -> None:
    assert {member.name: member.value for member in ScsiStatus} == {
        "GOOD": 0x00,
        "CHECK_CONDITION": 0x02,
        "CONDITION_MET": 0x04,
        "BUSY": 0x08,
        "RESERVATION_CONFLICT": 0x18,
        "TASK_SET_FULL": 0x28,
        "ACA_ACTIVE": 0x30,
        "TASK_ABORTED": 0x40,
    }


# The meanings are written out, so a wrong one can't pass unnoticed.
@pytest.mark.parametrize(
    ("scsi_status", "meaning"),
    [
        (ScsiStatus.CHECK_CONDITION, "the drive didn't say why"),
        (ScsiStatus.CONDITION_MET, "unexpected answer"),
        (ScsiStatus.BUSY, "the drive was busy"),
        (
            ScsiStatus.RESERVATION_CONFLICT,
            "another program has reserved the drive",
        ),
        (ScsiStatus.TASK_SET_FULL, "the drive had too many commands waiting"),
        (ScsiStatus.ACA_ACTIVE, "the drive is still handling an earlier error"),
        (ScsiStatus.TASK_ABORTED, "the command was canceled"),
        (SCSI_STATUS_NOT_LISTED, "unrecognized"),
    ],
)
def test_each_status_in_plain_words(
    scsi_status: int,
    meaning: str,
) -> None:
    assert scsi_status_meaning(scsi_status) == meaning
