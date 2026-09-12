"""Atomic text output: readers see either the previous file or the new one."""

import os
import tempfile
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Replace a UTF-8 file only after writing it successfully on the same volume."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent,
        prefix=path.name, suffix=".tmp", delete=False,
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, path)
    finally:
        Path(handle.name).unlink(missing_ok=True)
