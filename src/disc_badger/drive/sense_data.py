# SPDX-License-Identifier: GPL-3.0-or-later
"""Sense data: a drive's report of an error or other condition."""

# The layouts are from SPC-3, section 4.5; `drive` lists the drafts with their
# links.

from dataclasses import dataclass
from enum import IntEnum, unique
from typing import Self

# The fields every standard format keeps in the same place (tables 13 and 26):
# the response code in the low 7 bits of byte 0, and in byte 7 the number of
# bytes after it.
_RESPONSE_CODE_MASK = 0x7F
_LENGTH_BYTE = 7
_HEADER_SIZE_BYTES = 8
_SENSE_KEY_MASK = 0x0F


@dataclass(frozen=True)
class _Format:
    """Where one standard format keeps the sense key, ASC and ASCQ."""

    sense_key_byte: int
    asc_byte: int
    ascq_byte: int
    minimum_size_bytes: int
    """The fewest bytes that hold all three."""


# Fixed format is in table 26, descriptor format in table 13. Each minimum size
# is the bytes up to and including the ASCQ.
_FIXED = _Format(
    sense_key_byte=2,
    asc_byte=12,
    ascq_byte=13,
    minimum_size_bytes=14,
)
_DESCRIPTOR = _Format(
    sense_key_byte=1,
    asc_byte=2,
    ascq_byte=3,
    minimum_size_bytes=4,
)


# The values are from section 4.5.1, table 12, which describes each code by its
# error type and format. A current error is the command that failed; a deferred
# one is an earlier command that failed later. 7Fh, vendor specific, isn't named
# here: any code not listed is read the same way.
@unique
class ResponseCode(IntEnum):
    """Which kind of sense data it is: current or deferred, and its format."""

    CURRENT_FIXED = 0x70
    DEFERRED_FIXED = 0x71
    CURRENT_DESCRIPTOR = 0x72
    DEFERRED_DESCRIPTOR = 0x73


# Each standard response code's format.
_FORMATS: dict[int, _Format] = {
    ResponseCode.CURRENT_FIXED: _FIXED,
    ResponseCode.DEFERRED_FIXED: _FIXED,
    ResponseCode.CURRENT_DESCRIPTOR: _DESCRIPTOR,
    ResponseCode.DEFERRED_DESCRIPTOR: _DESCRIPTOR,
}
_DEFERRED_RESPONSE_CODES = frozenset(
    {ResponseCode.DEFERRED_FIXED, ResponseCode.DEFERRED_DESCRIPTOR},
)


# The values are from T10's list of sense keys:
# https://www.t10.org/lists/2sensekey.htm. SPC-3's table 27 has the same keys,
# except that it lists Fh, COMPLETED, as reserved. Ch is obsolete and isn't
# listed.
@unique
class SenseKey(IntEnum):
    """What kind of condition sense data reports."""

    NO_SENSE = 0x0
    RECOVERED_ERROR = 0x1
    NOT_READY = 0x2
    MEDIUM_ERROR = 0x3
    HARDWARE_ERROR = 0x4
    ILLEGAL_REQUEST = 0x5
    UNIT_ATTENTION = 0x6
    DATA_PROTECT = 0x7
    BLANK_CHECK = 0x8
    VENDOR_SPECIFIC = 0x9
    COPY_ABORTED = 0xA
    ABORTED_COMMAND = 0xB
    VOLUME_OVERFLOW = 0xD
    MISCOMPARE = 0xE
    COMPLETED = 0xF


# What each sense key means, in plain words.
_SENSE_KEY_MEANINGS: dict[int, str] = {
    SenseKey.NO_SENSE: "the drive gave no reason",
    SenseKey.RECOVERED_ERROR: "the drive recovered from an error",
    SenseKey.NOT_READY: "the drive wasn't ready",
    SenseKey.MEDIUM_ERROR: "the drive couldn't read the disc",
    SenseKey.HARDWARE_ERROR: "the drive reported a hardware fault",
    SenseKey.ILLEGAL_REQUEST: "the drive rejected the request",
    SenseKey.UNIT_ATTENTION: "the drive's state changed, such as a new disc",
    SenseKey.DATA_PROTECT: "the disc is protected against this",
    SenseKey.BLANK_CHECK: "the drive found a blank area of the disc",
    SenseKey.VENDOR_SPECIFIC: "a reason specific to this drive",
    SenseKey.COPY_ABORTED: "a copy was stopped",
    SenseKey.ABORTED_COMMAND: "the drive gave up on the command",
    SenseKey.VOLUME_OVERFLOW: "the end of the disc was reached",
    SenseKey.MISCOMPARE: "the data didn't match",
    SenseKey.COMPLETED: "the command finished with a note from the drive",
}


@dataclass(frozen=True)
class SenseData:
    """A drive's report of an error or other condition (SPC-3 section 4.5).

    The drive sends it with the status CHECK CONDITION, or in answer to REQUEST
    SENSE. It usually says why a command failed, but can also report a recovered
    error, a changed disc (UNIT ATTENTION), or an earlier command that failed
    later (a deferred error).

    Its sense key says what kind of condition it is (such as ILLEGAL REQUEST),
    and the additional sense code (ASC) and its qualifier (ASCQ) say which one
    (such as MEDIUM REMOVAL PREVENTED). It comes in two formats, told apart by
    the response code in the low 7 bits of byte 0. Both keep in byte 7 the
    number of bytes after it. Response code 7Fh is vendor specific, with a
    layout the standard doesn't define.

    Fixed format, response codes 70h and 71h (section 4.5.3, table 26)::

        byte 0       bit 7: VALID; bits 6-0: RESPONSE CODE
        byte 1       obsolete
        byte 2       bit 7: FILEMARK; bit 6: EOM; bit 5: ILI; bit 4: reserved;
                     bits 3-0: SENSE KEY
        bytes 3-6    INFORMATION
        byte 7       ADDITIONAL SENSE LENGTH (n - 7)
        bytes 8-11   COMMAND-SPECIFIC INFORMATION
        byte 12      ADDITIONAL SENSE CODE
        byte 13      ADDITIONAL SENSE CODE QUALIFIER
        byte 14      FIELD REPLACEABLE UNIT CODE
        bytes 15-17  byte 15, bit 7: SKSV; the rest: SENSE KEY SPECIFIC
        bytes 18-n   additional sense bytes

    Descriptor format, response codes 72h and 73h (section 4.5.2, table 13)::

        byte 0       bit 7: reserved; bits 6-0: RESPONSE CODE
        byte 1       bits 7-4: reserved; bits 3-0: SENSE KEY
        byte 2       ADDITIONAL SENSE CODE
        byte 3       ADDITIONAL SENSE CODE QUALIFIER
        bytes 4-6    reserved
        byte 7       ADDITIONAL SENSE LENGTH (n - 7)
        bytes 8-n    sense data descriptors

    Only `parse` builds one.
    """

    raw: bytes
    """The bytes the drive sent, trimmed to the length they give."""
    deferred: bool
    """Whether it reports an earlier command that failed later, not this one.

    Response codes 71h and 73h mark such a deferred error.
    """
    sense_key: int | None
    """What kind of condition it is, or None if the format doesn't say.

    T10 lists what each key means: https://www.t10.org/lists/2sensekey.htm
    """
    asc: int | None
    """The additional sense code: which condition, or None.

    T10 lists what each ASC and ASCQ pair means:
    https://www.t10.org/lists/asc-num.htm
    """
    ascq: int | None
    """The additional sense code qualifier: detail on the ASC, or None."""

    @classmethod
    def parse(cls, sense_buffer: bytes) -> Self | None:
        """Return the sense data in a buffer that may hold more.

        Return None if the drive left the buffer as zeros. Sense data in a
        format the standard doesn't define is kept whole, with no sense key.
        """
        if not any(sense_buffer):
            return None
        response_code = sense_buffer[0] & _RESPONSE_CODE_MASK
        sense_format = _FORMATS.get(response_code)
        if sense_format is None:
            return cls(
                raw=sense_buffer,
                deferred=False,
                sense_key=None,
                asc=None,
                ascq=None,
            )
        deferred = response_code in _DEFERRED_RESPONSE_CODES
        # Trim to the length the sense data gives, once it's long enough to say.
        raw = sense_buffer
        if len(raw) >= _HEADER_SIZE_BYTES:
            raw = raw[: _HEADER_SIZE_BYTES + raw[_LENGTH_BYTE]]
        if len(raw) < sense_format.minimum_size_bytes:
            return cls(
                raw=raw,
                deferred=deferred,
                sense_key=None,
                asc=None,
                ascq=None,
            )
        return cls(
            raw=raw,
            deferred=deferred,
            sense_key=raw[sense_format.sense_key_byte] & _SENSE_KEY_MASK,
            asc=raw[sense_format.asc_byte],
            ascq=raw[sense_format.ascq_byte],
        )

    def sense_report(self) -> str | None:
        """Return the sense key, ASC and ASCQ as people write them, or None.

        For example "sense 5/53/02": the key as one hex digit, the ASC and ASCQ
        as two. A deferred error reads "deferred sense 5/53/02". None when the
        format doesn't give them.
        """
        if self.sense_key is None or self.asc is None or self.ascq is None:
            return None
        sense_code = f"{self.sense_key:X}/{self.asc:02X}/{self.ascq:02X}"
        if self.deferred:
            return f"deferred sense {sense_code}"
        return f"sense {sense_code}"

    def sense_key_meaning(self) -> str | None:
        """Return what the sense key means, in plain words, or None.

        For example "the drive rejected the request" for ILLEGAL REQUEST. None
        when the format doesn't give a sense key.
        """
        if self.sense_key is None:
            return None
        return _SENSE_KEY_MEANINGS.get(self.sense_key, "unrecognized")
