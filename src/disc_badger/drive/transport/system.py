# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect to a drive through the modules for this operating system."""

import sys

from disc_badger.drive.transport import Transport

# Each operating system's modules are loaded only on that system.
if sys.platform == "win32":
    from disc_badger.drive.transport import (
        transport_windows,
        transport_windows_c,
    )


def _unsupported() -> NotImplementedError:
    """Return the error for an operating system without a transport."""
    return NotImplementedError(f"Disc Badger doesn't support {sys.platform}.")


def connect(drive_name: str) -> Transport:
    """Connect to a drive by its normalized name, such as `D:`.

    Raise DriveConnectError if the drive can't be used or reached.
    """
    if sys.platform == "win32":
        return transport_windows.TransportWindows(
            drive_name=drive_name,
            c_calls=transport_windows_c,
        )
    raise _unsupported()


def normalize_name(name: str) -> str:
    """Turn a drive name into this system's form, or raise ValueError."""
    if sys.platform == "win32":
        return transport_windows.normalize_name(name)
    raise _unsupported()


def check_64_bit() -> None:
    """Refuse to run on 32-bit Python, whose structures no system can use."""
    # Python's documentation gives this test for a 64-bit interpreter:
    # https://docs.python.org/3/library/platform.html#platform.architecture
    if sys.maxsize <= 2**32:
        raise RuntimeError("Disc Badger needs 64-bit Python, not 32-bit")


# Check once, as this module loads, so Disc Badger refuses to run rather than
# hand any system a structure laid out for the wrong pointer size. Only the
# tests call it again.
check_64_bit()
