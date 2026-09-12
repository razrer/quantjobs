"""A failed replacement must leave the last usable board intact."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantscraper import files


class AtomicTextTest(unittest.TestCase):
    def test_failed_replace_preserves_original_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.js"
            path.write_text("old", encoding="utf-8")
            with patch.object(files.os, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    files.write_text(path, "new")
            self.assertEqual(path.read_text(), "old")
            self.assertEqual(list(Path(directory).iterdir()), [path])
            files.write_text(path, "Öhman\n")
            self.assertEqual(path.read_bytes(), "Öhman\n".encode())
