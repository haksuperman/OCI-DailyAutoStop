from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.compartments import load_exception_entries


class LoadExceptionEntriesTest(unittest.TestCase):
    def test_comments_and_blank_lines_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "exceptions.txt"
            path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "",
                        "finance-shared",
                        "  ",
                        "ocid1.compartment.oc1..example",
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                load_exception_entries(path),
                ["finance-shared", "ocid1.compartment.oc1..example"],
            )


if __name__ == "__main__":
    unittest.main()
