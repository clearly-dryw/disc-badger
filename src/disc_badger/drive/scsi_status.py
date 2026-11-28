# SPDX-License-Identifier: GPL-3.0-or-later
"""SCSI status: how a drive says a command went, and what each status means."""

from enum import IntEnum, unique


# The values are from T10's list of SCSI status codes:
# https://www.t10.org/lists/2status.htm. T10 is the committee that writes the
# SCSI standards. The codes are defined in its SCSI Architecture Model (SAM),
# which only T10 members can read, so this public list is the source.
@unique
class ScsiStatus(IntEnum):
    """How a drive says a command went: the status byte it returns.

    `GOOD` means the command worked. `CHECK_CONDITION` means it failed, and the
    drive's sense data says why.
    """

    GOOD = 0x00
    CHECK_CONDITION = 0x02
    CONDITION_MET = 0x04
    BUSY = 0x08
    RESERVATION_CONFLICT = 0x18
    TASK_SET_FULL = 0x28
    ACA_ACTIVE = 0x30
    TASK_ABORTED = 0x40


# What each status means, in plain words, when a command didn't work. GOOD is
# never shown, and CHECK CONDITION only when the sense data doesn't say why.
# Only PRE-FETCH, which Disc Badger never sends, answers CONDITION MET.
_SCSI_STATUS_MEANINGS: dict[int, str] = {
    ScsiStatus.CHECK_CONDITION: "the drive didn't say why",
    ScsiStatus.CONDITION_MET: "unexpected answer",
    ScsiStatus.BUSY: "the drive was busy",
    ScsiStatus.RESERVATION_CONFLICT: "another program has reserved the drive",
    ScsiStatus.TASK_SET_FULL: "the drive had too many commands waiting",
    ScsiStatus.ACA_ACTIVE: "the drive is still handling an earlier error",
    ScsiStatus.TASK_ABORTED: "the command was canceled",
}


def scsi_status_meaning(scsi_status: int) -> str:
    """Return what a status that isn't GOOD means, in plain words.

    For example "the drive was busy" for BUSY, or "unrecognized" for a status
    T10's list doesn't have.
    """
    return _SCSI_STATUS_MEANINGS.get(scsi_status, "unrecognized")
