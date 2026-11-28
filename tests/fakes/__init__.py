# SPDX-License-Identifier: GPL-3.0-or-later
"""Stand-ins the tests use in place of real drives, systems and transports.

Each module stands in for the source module of the same name. This package
re-exports every name, so tests import them from `tests.fakes` itself.
"""

from tests.fakes.system import pretend_windows
from tests.fakes.transport import (
    GOOD,
    OS_FAILED,
    REFUSED,
    SENSE_DATA_TRAY_LOCKED_DESCRIPTOR,
    SENSE_DATA_TRAY_LOCKED_FIXED,
    TransportFake,
)
from tests.fakes.transport_windows_c import (
    DEVICE_HANDLE,
    ERROR_GEN_FAILURE,
    TransportWindowsCFake,
    WindowsAnswer,
)

__all__ = [
    "DEVICE_HANDLE",
    "ERROR_GEN_FAILURE",
    "GOOD",
    "OS_FAILED",
    "REFUSED",
    "SENSE_DATA_TRAY_LOCKED_DESCRIPTOR",
    "SENSE_DATA_TRAY_LOCKED_FIXED",
    "TransportFake",
    "TransportWindowsCFake",
    "WindowsAnswer",
    "pretend_windows",
]
