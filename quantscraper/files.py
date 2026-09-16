"""Atomic text output: readers see either the previous file or the new one."""

import ctypes
import os
import tempfile
from pathlib import Path


def _replace_windows(source: str | Path, destination: str | Path) -> None:
    """Atomically replace an existing Windows file with its native API.

    ``os.replace`` uses MoveFileEx on Windows. On this machine that operation
    can create and rename ordinary files but is denied when replacing the
    versioned human-label sheet. ReplaceFile is Windows' purpose-built atomic
    file replacement and preserves the destination's ACL and metadata.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = (
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p,
    )
    replace_file.restype = ctypes.c_int
    if not replace_file(str(destination), str(source), None, 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def atomic_replace(source: str | Path, destination: str | Path) -> None:
    """Atomically move ``source`` over ``destination`` on this platform."""
    destination = Path(destination)
    if os.name == "nt" and destination.exists():
        _replace_windows(source, destination)
    else:
        os.replace(source, destination)


def write_text(path: Path, text: str) -> None:
    """Replace a UTF-8 file only after writing it successfully on the same volume."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent,
        prefix=path.name, suffix=".tmp", delete=False,
    )
    try:
        with handle:
            handle.write(text)
        atomic_replace(handle.name, path)
    finally:
        Path(handle.name).unlink(missing_ok=True)
