from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import context_compile
import context_lint
from safe_io import PROTOCOL_VERSION, SafeIOError, require_version


class ReleaseContractTests(unittest.TestCase):
    def load(self, rel: str):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    def test_public_protocol_is_1_0(self):
        self.assertEqual(PROTOCOL_VERSION, "1.0")
        require_version(self.load("examples/sample-state.json"), label="state")
        require_version(self.load("examples/semantic-candidates.json"), label="semantic candidates")

    def test_stale_protocol_version_is_rejected(self):
        state = self.load("examples/sample-state.json")
        state["version"] = "0.8"
        with self.assertRaises(SafeIOError):
            require_version(state, label="state")

    def test_cli_rejects_stale_state_protocol(self):
        state = self.load("examples/sample-state.json")
        state["version"] = "0.8"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            cp = subprocess.run(
                [sys.executable, str(SCRIPTS / "context_lint.py"), str(path), "--strict"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(cp.returncode, 2)
        self.assertIn("unsupported state version", cp.stderr)

    def test_retrieval_gate_report_declares_protocol_version(self):
        state = self.load("examples/sample-state.json")
        task = self.load("examples/compiler-task.json")
        candidates = self.load("examples/semantic-candidates.json")
        report = context_compile.gate_semantic_candidates(state, task, candidates)
        self.assertEqual(report["version"], PROTOCOL_VERSION)

    def test_retriever_cannot_use_stale_candidate_protocol(self):
        state = self.load("examples/sample-state.json")
        task = self.load("examples/compiler-task.json")
        candidates = copy.deepcopy(self.load("examples/semantic-candidates.json"))
        candidates["version"] = "0.8"
        with self.assertRaises(SafeIOError):
            context_compile.gate_semantic_candidates(state, task, candidates)

    def test_shipped_state_template_is_lint_clean(self):
        template = self.load("templates/state.json")
        require_version(template, label="state template")
        findings = context_lint.lint(template)
        self.assertFalse([f for f in findings if f.severity in {"ERROR", "WARN"}], findings)


if __name__ == "__main__":
    unittest.main()
