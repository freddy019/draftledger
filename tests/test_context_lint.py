import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("context_lint", ROOT / "scripts" / "context_lint.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ContextLintTests(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))

    def test_sample_has_no_errors_or_warnings(self):
        findings = MODULE.lint(self.load("sample-state.json"))
        bad = [f for f in findings if f.severity in {"ERROR", "WARN"}]
        self.assertEqual([], bad)

    def test_broken_state_detects_material_issues(self):
        findings = MODULE.lint(self.load("broken-state.json"))
        codes = {f.code for f in findings}
        self.assertIn("ACTIVE_INSTRUCTION_COLLISION", codes)
        self.assertIn("STALE_FACT_DEP", codes)
        self.assertIn("INVALID_ASSUMPTION_DEP", codes)
        self.assertIn("DANGLING_INSTRUCTION_DEP", codes)


    def test_untrusted_active_instruction_is_error(self):
        state = self.load("sample-state.json")
        for item in state["instructions"]:
            if item["id"] == "I-009":
                item["trust_level"] = "untrusted"
        findings = MODULE.lint(state)
        self.assertIn("UNTRUSTED_CONTROL", {f.code for f in findings})

    def test_non_instruction_cannot_claim_control_authority(self):
        state = self.load("sample-state.json")
        state["facts"][0]["authority"] = "control"
        findings = MODULE.lint(state)
        self.assertIn("DATA_AUTHORITY_ESCALATION", {f.code for f in findings})


if __name__ == "__main__":
    unittest.main()
