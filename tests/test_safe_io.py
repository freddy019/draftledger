from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("safe_io", ROOT / "scripts" / "safe_io.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SafeIOTests(unittest.TestCase):
    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(MODULE.SafeIOError):
            MODULE.loads_json_strict('{"a":1,"a":2}')

    def test_non_finite_numbers_are_rejected(self):
        with self.assertRaises(MODULE.SafeIOError):
            MODULE.loads_json_strict('{"x":NaN}')

    def test_depth_limit_is_enforced(self):
        value = 0
        for _ in range(12):
            value = [value]
        text = json.dumps(value)
        with self.assertRaises(MODULE.SafeIOError):
            MODULE.loads_json_strict(text, max_depth=5)

    def test_node_limit_is_enforced(self):
        text = json.dumps({"x": list(range(20))})
        with self.assertRaises(MODULE.SafeIOError):
            MODULE.loads_json_strict(text, max_nodes=5)

    def test_file_size_limit_is_enforced_before_parse(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "large.json"
            p.write_text('{"x":"' + ('a' * 100) + '"}', encoding="utf-8")
            with self.assertRaises(MODULE.SafeIOError):
                MODULE.read_json(p, max_bytes=16)

    def test_atomic_write_replaces_symlink_not_target(self):
        if os.name != "posix":
            self.skipTest("symlink semantics tested on POSIX")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target.txt"
            target.write_text("secret", encoding="utf-8")
            out = root / "out.txt"
            out.symlink_to(target)
            MODULE.atomic_write_text(out, "safe")
            self.assertEqual(target.read_text(encoding="utf-8"), "secret")
            self.assertFalse(out.is_symlink())
            self.assertEqual(out.read_text(encoding="utf-8"), "safe")


if __name__ == "__main__":
    unittest.main()
