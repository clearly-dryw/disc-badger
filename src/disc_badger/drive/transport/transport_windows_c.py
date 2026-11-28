# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows: the calls into Windows that `TransportWindows` makes.

Each function wraps one Windows function, taking and returning plain Python
values. `system` passes this module to `TransportWindows`; tests pass a fake.
"""

# ctypes calls Windows directly, so Python can't catch a mistake here: a wrong
# argument type or structure field can crash Disc Badger or corrupt its memory.
# Check every declaration and call against Microsoft's documentation, and keep
# everything else in `transport_windows`, where the tests reach it.

import ctypes
import sys

from disc_badger.drive.transport.transport_windows import Handle

# Refuse to load on another system, where the Windows functions don't exist.
# This also tells pyright to skip the rest of the file there.
if sys.platform != "win32":
    raise ImportError("Disc Badger's Windows calls run only on Windows.")

from ctypes import wintypes

# The handle CreateFileW returns when it fails, which handleapi.h defines as
# (HANDLE)-1. Microsoft's windows-sys bindings, generated from the SDK, give the
# same value: https://docs.rs/windows-sys/0.59.0/windows_sys/
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# Load kernel32.dll, the library through which Windows offers programs its basic
# functions, such as those for files and devices. Every function used here comes
# from it, as the Requirements table on each one's page (linked below) says.
# use_last_error keeps each call's error code for ctypes.get_last_error().
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Declare the C argument and return types of the Windows functions used, so
# ctypes converts values correctly. Each is named `_c_win32_…`: `_c_` marks a
# call into C, which ctypes can't check, so each call needs extra care.
#
# ctypes passes arguments by position, so each argtypes tuple lists the
# parameters in exactly the order of the function's syntax on its page; the
# comment on each line is the parameter's name there. A pointer to a structure
# Disc Badger always passes as None is declared as a plain pointer (LPVOID), and
# its comment names the documented type.

# https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-getdrivetypew
_c_win32_get_drive_type = _kernel32.GetDriveTypeW
_c_win32_get_drive_type.argtypes = (wintypes.LPCWSTR,)  # lpRootPathName
_c_win32_get_drive_type.restype = wintypes.UINT

# https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
_c_win32_create_file = _kernel32.CreateFileW
_c_win32_create_file.argtypes = (
    wintypes.LPCWSTR,  # lpFileName
    wintypes.DWORD,  # dwDesiredAccess
    wintypes.DWORD,  # dwShareMode
    wintypes.LPVOID,  # lpSecurityAttributes: LPSECURITY_ATTRIBUTES, always None
    wintypes.DWORD,  # dwCreationDisposition
    wintypes.DWORD,  # dwFlagsAndAttributes
    wintypes.HANDLE,  # hTemplateFile
)
_c_win32_create_file.restype = wintypes.HANDLE

# https://learn.microsoft.com/windows/win32/api/ioapiset/nf-ioapiset-deviceiocontrol
_c_win32_device_io_control = _kernel32.DeviceIoControl
_c_win32_device_io_control.argtypes = (
    wintypes.HANDLE,  # hDevice
    wintypes.DWORD,  # dwIoControlCode
    wintypes.LPVOID,  # lpInBuffer
    wintypes.DWORD,  # nInBufferSize
    wintypes.LPVOID,  # lpOutBuffer
    wintypes.DWORD,  # nOutBufferSize
    wintypes.LPDWORD,  # lpBytesReturned
    wintypes.LPVOID,  # lpOverlapped: LPOVERLAPPED, always None
)
_c_win32_device_io_control.restype = wintypes.BOOL

# https://learn.microsoft.com/windows/win32/api/handleapi/nf-handleapi-closehandle
_c_win32_close_handle = _kernel32.CloseHandle
_c_win32_close_handle.argtypes = (wintypes.HANDLE,)  # hObject
_c_win32_close_handle.restype = wintypes.BOOL


def get_drive_type(root_path_name: str) -> int:
    r"""Return what kind of drive a root directory, such as `D:\`, is on."""
    drive_type: int = _c_win32_get_drive_type(
        root_path_name,  # lpRootPathName
    )
    return drive_type


def create_file(
    file_name: str,
    desired_access: int,
    share_mode: int,
    creation_disposition: int,
) -> Handle | None:
    """Return a handle to a file or device, or None if Windows refused.

    `last_error` then says why.
    """
    handle: int | None = _c_win32_create_file(
        file_name,  # lpFileName
        desired_access,  # dwDesiredAccess
        share_mode,  # dwShareMode
        None,  # lpSecurityAttributes
        creation_disposition,  # dwCreationDisposition
        0,  # dwFlagsAndAttributes
        None,  # hTemplateFile
    )
    if handle is None or handle == INVALID_HANDLE_VALUE:
        return None
    return Handle(handle)


def device_io_control(
    device_handle: Handle,
    io_control_code: int,
    in_out_buffer: ctypes.Structure,
) -> bool:
    """Send a buffer to a device, which answers in the same buffer.

    Return whether Windows delivered it; if not, `last_error` says why.
    """
    buffer_size_bytes = ctypes.sizeof(in_out_buffer)
    # Windows needs somewhere to write how many bytes it returned, though the
    # answer is read from the buffer's own fields.
    returned_size_bytes = wintypes.DWORD(0)
    delivered: int = _c_win32_device_io_control(
        device_handle,  # hDevice
        io_control_code,  # dwIoControlCode
        ctypes.byref(in_out_buffer),  # lpInBuffer
        buffer_size_bytes,  # nInBufferSize
        ctypes.byref(in_out_buffer),  # lpOutBuffer
        buffer_size_bytes,  # nOutBufferSize
        ctypes.byref(returned_size_bytes),  # lpBytesReturned
        None,  # lpOverlapped
    )
    return bool(delivered)


def close_handle(device_handle: Handle) -> bool:
    """Close a handle; return whether Windows closed it."""
    closed: int = _c_win32_close_handle(
        device_handle,  # hObject
    )
    return bool(closed)


def last_error() -> int:
    """Return Windows' error code for the last call.

    It means something only after a call failed.
    """
    return ctypes.get_last_error()
