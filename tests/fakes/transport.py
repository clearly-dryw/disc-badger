# SPDX-License-Identifier: GPL-3.0-or-later
"""Stand-ins for a transport: `TransportFake` and the answers it gives."""

from typing import ClassVar

from disc_badger.drive.commands import DriveCommand
from disc_badger.drive.scsi_status import ScsiStatus
from disc_badger.drive.sense_data import SenseData
from disc_badger.drive.transport import (
    CommandResult,
    DriveAnswer,
    OsFailure,
    OsFailureKind,
    Transport,
    transport_windows,
)

# Sense data for a refusal because the tray is locked: sense key 5h ILLEGAL
# REQUEST, ASC/ASCQ 53h/02h MEDIUM REMOVAL PREVENTED. The codes are from T10's
# lists:
#
# - https://www.t10.org/lists/2sensekey.htm
# - https://www.t10.org/lists/asc-num.htm
#
# In fixed format (SPC-3 section 4.5.3): response code 70h in byte 0, the key in
# byte 2, additional sense length 0Ah in byte 7 (18 bytes in all), and the ASC
# and ASCQ in bytes 12 and 13.
SENSE_DATA_TRAY_LOCKED_FIXED = bytes.fromhex(
    "70 00 05 00 00 00 00 0A 00 00 00 00 53 02 00 00 00 00",
)
# In descriptor format (section 4.5.2): response code 72h in byte 0, the key,
# ASC and ASCQ in bytes 1 to 3, and no descriptors after byte 7.
SENSE_DATA_TRAY_LOCKED_DESCRIPTOR = bytes.fromhex("72 05 53 02 00 00 00 00")

GOOD = DriveAnswer(scsi_status=ScsiStatus.GOOD, sense_data=None)
REFUSED = DriveAnswer(
    scsi_status=ScsiStatus.CHECK_CONDITION,
    sense_data=SenseData.parse(SENSE_DATA_TRAY_LOCKED_FIXED),
)
# A command the OS couldn't deliver, so the drive never answered: a timeout, as
# Windows reports one when a drive stops answering.
_SEM_TIMEOUT = transport_windows.ErrorCode.SEM_TIMEOUT
OS_FAILED = OsFailure(
    kind=OsFailureKind.TIMEOUT,
    os_error=_SEM_TIMEOUT,
    os_report=f"Windows error {_SEM_TIMEOUT}",
)


class TransportFake(Transport):
    """Records the commands it is sent and answers from a list.

    A command with no answer left fails the test, and so does an answer left
    unused when the test ends (`check_all_answered`, which `conftest.py` runs
    after every test).
    """

    made: ClassVar[list["TransportFake"]] = []
    """Every fake made since the last `check_all_answered`."""

    def __init__(self, *answers: CommandResult) -> None:
        self.answers = list(answers)
        self.sent: list[tuple[bytes, int]] = []
        self.disconnected = False
        TransportFake.made.append(self)

    def disconnect(self) -> None:
        self.disconnected = True

    def send(self, command: DriveCommand) -> CommandResult:
        if self.disconnected:
            raise RuntimeError("the fake transport is disconnected")
        self.sent.append((command.cdb, command.timeout_s))
        if not self.answers:
            message = f"no answer left for CDB [{command.cdb.hex(' ')}]"
            raise AssertionError(message)
        return self.answers.pop(0)

    @classmethod
    def check_all_answered(cls) -> None:
        """Fail if a fake made since the last check has answers left over.

        A leftover answer means a command the test expected was never sent.
        """
        unused = [fake.answers for fake in cls.made if fake.answers]
        cls.made.clear()
        if unused:
            raise AssertionError(f"answers never used: {unused}")
