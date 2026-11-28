# SPDX-License-Identifier: GPL-3.0-or-later
"""Sense data: trimmed to what the drive sent, and read in both formats."""

import hashlib

import pytest

from disc_badger.drive.sense_data import ResponseCode, SenseData, SenseKey
from tests.fakes import (
    SENSE_DATA_TRAY_LOCKED_DESCRIPTOR,
    SENSE_DATA_TRAY_LOCKED_FIXED,
)

# The Windows transport reads sense data into a buffer this size. It's written
# out, not read from the module, so a wrong number there can't pass unnoticed.
SENSE_BUFFER_SIZE_BYTES = 252

# The tray is locked, in each format, and the sense key, ASC and ASCQ that say
# so: 5h ILLEGAL REQUEST, 53h/02h MEDIUM REMOVAL PREVENTED.
FIXED = SENSE_DATA_TRAY_LOCKED_FIXED
DESCRIPTOR = SENSE_DATA_TRAY_LOCKED_DESCRIPTOR
TRAY_LOCKED = (0x5, 0x53, 0x02)

# A sense key T10's list doesn't have: Ch, now obsolete.
SENSE_KEY_NOT_LISTED = 0xC


def _padded(sense_sent: bytes) -> bytes:
    """Return sense data as a transport reads it: at the start of a buffer."""
    return sense_sent.ljust(SENSE_BUFFER_SIZE_BYTES, b"\0")


def _key_asc_ascq(sense_data: SenseData) -> tuple[int | None, ...]:
    """Return the three codes, to compare them at once."""
    return (sense_data.sense_key, sense_data.asc, sense_data.ascq)


@pytest.mark.parametrize(
    "sense_buffer",
    [b"", bytes(SENSE_BUFFER_SIZE_BYTES)],
)
def test_no_sense_data(sense_buffer: bytes) -> None:
    assert SenseData.parse(sense_buffer) is None


@pytest.mark.parametrize("sense_sent", [FIXED, DESCRIPTOR])
def test_both_formats_are_trimmed_and_read(sense_sent: bytes) -> None:
    sense_data = SenseData.parse(_padded(sense_sent))
    assert sense_data is not None
    assert sense_data.raw == sense_sent
    assert _key_asc_ascq(sense_data) == TRAY_LOCKED


@pytest.mark.parametrize("sense_sent", [FIXED, DESCRIPTOR])
def test_a_current_error_isnt_deferred(sense_sent: bytes) -> None:
    sense_data = SenseData.parse(_padded(sense_sent))
    assert sense_data is not None
    assert not sense_data.deferred


# The same sense data, sent as a deferred error in each format.
@pytest.mark.parametrize(
    "deferred_sent",
    [
        bytes([ResponseCode.DEFERRED_FIXED]) + FIXED[1:],
        bytes([ResponseCode.DEFERRED_DESCRIPTOR]) + DESCRIPTOR[1:],
    ],
    ids=["fixed format", "descriptor format"],
)
def test_deferred_errors_are_read_the_same_way_and_marked(
    deferred_sent: bytes,
) -> None:
    sense_data = SenseData.parse(_padded(deferred_sent))
    assert sense_data is not None
    assert sense_data.deferred
    assert _key_asc_ascq(sense_data) == TRAY_LOCKED
    assert sense_data.sense_report() == "deferred sense 5/53/02"


def test_the_valid_bit_doesnt_change_the_format() -> None:
    valid = bytes([0xF0]) + FIXED[1:]  # 70h with bit 7, VALID, set
    sense_data = SenseData.parse(_padded(valid))
    assert sense_data is not None
    assert _key_asc_ascq(sense_data) == TRAY_LOCKED


def test_sense_data_too_short_for_its_codes_has_none() -> None:
    # Fixed format whose length says 8 bytes in all: too few to hold the ASC.
    short = bytes.fromhex("70 00 05 00 00 00 00 00")
    sense_data = SenseData.parse(_padded(short))
    assert sense_data is not None
    assert sense_data.raw == short
    assert _key_asc_ascq(sense_data) == (None, None, None)


def test_a_buffer_shorter_than_its_length_field_is_kept_whole() -> None:
    sense_data = SenseData.parse(FIXED[:12])
    assert sense_data is not None
    assert sense_data.raw == FIXED[:12]
    assert _key_asc_ascq(sense_data) == (None, None, None)


def test_a_vendor_format_is_kept_whole_without_codes() -> None:
    vendor = _padded(b"\x7f\x01\x02")
    sense_data = SenseData.parse(vendor)
    assert sense_data is not None
    assert sense_data.raw == vendor
    assert _key_asc_ascq(sense_data) == (None, None, None)


def test_the_sense_report_as_people_write_it() -> None:
    sense_data = SenseData.parse(_padded(FIXED))
    assert sense_data is not None
    assert sense_data.sense_report() == "sense 5/53/02"


def test_the_sense_key_is_one_hex_digit() -> None:
    # Sense key Bh ABORTED COMMAND, ASC/ASCQ 00h/00h, in descriptor format.
    aborted = bytes.fromhex("72 0B 00 00 00 00 00 00")
    sense_data = SenseData.parse(_padded(aborted))
    assert sense_data is not None
    assert sense_data.sense_report() == "sense B/00/00"


def test_sense_data_without_codes_has_no_sense_report() -> None:
    sense_data = SenseData.parse(_padded(b"\x7f\x01\x02"))  # vendor format
    assert sense_data is not None
    assert sense_data.sense_report() is None


# The values are written out from SPC-3's table 12 rather than read from the
# module, so a wrong one can't pass unnoticed.
def test_the_response_codes_match_spc_3() -> None:
    assert {member.name: member.value for member in ResponseCode} == {
        "CURRENT_FIXED": 0x70,
        "DEFERRED_FIXED": 0x71,
        "CURRENT_DESCRIPTOR": 0x72,
        "DEFERRED_DESCRIPTOR": 0x73,
    }


# The values are written out from T10's list rather than read from the module,
# so a wrong one can't pass unnoticed.
def test_the_sense_keys_match_t10s_list() -> None:
    assert {member.name: member.value for member in SenseKey} == {
        "NO_SENSE": 0x0,
        "RECOVERED_ERROR": 0x1,
        "NOT_READY": 0x2,
        "MEDIUM_ERROR": 0x3,
        "HARDWARE_ERROR": 0x4,
        "ILLEGAL_REQUEST": 0x5,
        "UNIT_ATTENTION": 0x6,
        "DATA_PROTECT": 0x7,
        "BLANK_CHECK": 0x8,
        "VENDOR_SPECIFIC": 0x9,
        "COPY_ABORTED": 0xA,
        "ABORTED_COMMAND": 0xB,
        "VOLUME_OVERFLOW": 0xD,
        "MISCOMPARE": 0xE,
        "COMPLETED": 0xF,
    }


@pytest.mark.parametrize(
    ("sense_key", "meaning"),
    [
        (SenseKey.NO_SENSE, "the drive gave no reason"),
        (SenseKey.RECOVERED_ERROR, "the drive recovered from an error"),
        (SenseKey.NOT_READY, "the drive wasn't ready"),
        (SenseKey.MEDIUM_ERROR, "the drive couldn't read the disc"),
        (SenseKey.HARDWARE_ERROR, "the drive reported a hardware fault"),
        (SenseKey.ILLEGAL_REQUEST, "the drive rejected the request"),
        (
            SenseKey.UNIT_ATTENTION,
            "the drive's state changed, such as a new disc",
        ),
        (SenseKey.DATA_PROTECT, "the disc is protected against this"),
        (SenseKey.BLANK_CHECK, "the drive found a blank area of the disc"),
        (SenseKey.VENDOR_SPECIFIC, "a reason specific to this drive"),
        (SenseKey.COPY_ABORTED, "a copy was stopped"),
        (SenseKey.ABORTED_COMMAND, "the drive gave up on the command"),
        (SenseKey.VOLUME_OVERFLOW, "the end of the disc was reached"),
        (SenseKey.MISCOMPARE, "the data didn't match"),
        (
            SenseKey.COMPLETED,
            "the command finished with a note from the drive",
        ),
        (SENSE_KEY_NOT_LISTED, "unrecognized"),
    ],
)
def test_each_sense_key_in_plain_words(
    sense_key: int,
    meaning: str,
) -> None:
    sent = bytes([ResponseCode.CURRENT_DESCRIPTOR, sense_key, 0, 0, 0, 0, 0, 0])
    sense_data = SenseData.parse(_padded(sent))
    assert sense_data is not None
    assert sense_data.sense_key_meaning() == meaning


def test_sense_data_without_a_sense_key_has_no_meaning() -> None:
    sense_data = SenseData.parse(_padded(b"\x7f\x01\x02"))  # vendor format
    assert sense_data is not None
    assert sense_data.sense_key_meaning() is None


# Sense data comes from the drive, so the parser must cope with any bytes at
# all. The buffers are pseudo-random, from SHAKE-256: every run checks the same
# ones, so a failure can be reproduced.
FUZZ_CASES = 3000
MAX_FUZZ_SIZE_BYTES = 300  # more than the 252 a transport ever passes
SENSE_KEY_COUNT = 16  # the sense key is four bits
# Each case starts with one of these response codes, or a random byte (None), so
# every format is reached often: the standard ones, 7Fh (vendor specific), and
# F0h and F2h, which set the VALID bit.
FUZZ_RESPONSE_CODES = (*ResponseCode, 0x7F, 0xF0, 0xF2, None)


def _fuzz_buffer(case: int) -> bytes:
    """Return the pseudo-random sense buffer for one fuzzing case."""
    seed = case.to_bytes(length=4, byteorder="big")
    size_digest = hashlib.shake_256(b"size" + seed).digest(2)
    size_bytes = int.from_bytes(size_digest, byteorder="big")
    size_bytes %= MAX_FUZZ_SIZE_BYTES + 1
    data_digest = hashlib.shake_256(b"data" + seed).digest(size_bytes)
    sense_buffer = bytearray(data_digest)
    response_code = FUZZ_RESPONSE_CODES[case % len(FUZZ_RESPONSE_CODES)]
    if sense_buffer and response_code is not None:
        sense_buffer[0] = response_code
    return bytes(sense_buffer)


def _check_parse(sense_buffer: bytes) -> None:
    """Parse one buffer and check that what came out is consistent."""
    sense_data = SenseData.parse(sense_buffer)
    if sense_data is None:
        assert not any(sense_buffer)
        return
    assert sense_buffer.startswith(sense_data.raw)
    if sense_data.sense_key is None:
        assert sense_data.sense_report() is None
        assert sense_data.sense_key_meaning() is None
        return
    assert sense_data.sense_key in range(SENSE_KEY_COUNT)
    assert sense_data.sense_report() is not None
    assert sense_data.sense_key_meaning() is not None


def test_any_buffer_parses_without_error() -> None:
    for case in range(FUZZ_CASES):
        sense_buffer = _fuzz_buffer(case)
        try:
            _check_parse(sense_buffer)
        except Exception as error:
            error.add_note(f"fuzzing case {case}: [{sense_buffer.hex(' ')}]")
            raise
