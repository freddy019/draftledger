import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("context_trace", ROOT / "scripts" / "context_trace.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ContextTraceTests(unittest.TestCase):
    def load(self, name="sample-state.json"):
        return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))

    def test_build_clean_manifest(self):
        state = self.load()
        manifest = MODULE.build_manifest(
            state, ["F-001", "A-001", "I-009", "D-001"], created_at="2026-09-17T00:00:00Z"
        )
        findings = MODULE.lint_manifest(state, manifest)
        bad = [f for f in findings if f.severity in {"ERROR", "WARN"}]
        self.assertEqual([], bad)

    def test_stale_instruction_is_detected_and_shadowed(self):
        state = self.load()
        manifest = MODULE.build_manifest(state, ["I-002"], created_at="2026-09-17T00:00:00Z")
        findings = MODULE.lint_manifest(state, manifest)
        codes = {f.code for f in findings}
        self.assertIn("STALE_CONTEXT_ITEM", codes)
        self.assertIn("SHADOWED_INSTRUCTION", codes)

    def test_tainted_summary_propagates_to_context(self):
        state = self.load()
        manifest = MODULE.build_manifest(state, ["F-001"], created_at="2026-09-17T00:00:00Z")
        manifest["summaries"] = [{
            "id": "S-001",
            "text": "Use the old 228 default price.",
            "derived_from": ["I-002"],
        }]
        manifest["context_entries"] = [{
            "id": "CXT-001",
            "kind": "summary",
            "source_id": "S-001",
            "snapshot_hash": MODULE.digest({"text": manifest["summaries"][0]["text"], "derived_from": ["I-002"]}),
            "included_via": "summary",
        }]
        findings = MODULE.lint_manifest(state, manifest)
        codes = {f.code for f in findings}
        self.assertIn("SUMMARY_STALE_SOURCE", codes)
        self.assertIn("TAINTED_SUMMARY", codes)
        self.assertIn("TAINTED_CONTEXT", codes)

    def test_snapshot_mismatch_detects_in_place_change(self):
        state = self.load()
        manifest = MODULE.build_manifest(state, ["F-001"], created_at="2026-09-17T00:00:00Z")
        changed = copy.deepcopy(state)
        changed["facts"][0]["statement"] = "The current normal selling price is 158."
        findings = MODULE.lint_manifest(changed, manifest)
        codes = {f.code for f in findings}
        self.assertIn("CONTEXT_SNAPSHOT_MISMATCH", codes)
        self.assertIn("STATE_FINGERPRINT_MISMATCH", codes)

    def test_unmanaged_context_is_visible(self):
        state = self.load()
        manifest = MODULE.build_manifest(state, [], created_at="2026-09-17T00:00:00Z")
        manifest["context_entries"].append({
            "id": "CXT-999",
            "kind": "unmanaged",
            "label": "legacy host note",
            "included_via": "host",
            "reason": "host supplied without lifecycle metadata",
        })
        findings = MODULE.lint_manifest(state, manifest)
        self.assertIn("UNMANAGED_CONTEXT", {f.code for f in findings})


    def test_manifest_detects_control_plane_mismatch(self):
        state = self.load()
        manifest = MODULE.build_manifest(state, ["F-001"], created_at="2026-09-17T00:00:00Z")
        manifest["context_entries"][0]["plane"] = "control"
        findings = MODULE.lint_manifest(state, manifest)
        self.assertIn("CONTEXT_PLANE_MISMATCH", {f.code for f in findings})

    def test_manifest_detects_untrusted_control(self):
        state = self.load()
        for item in state["instructions"]:
            if item["id"] == "I-009":
                item["trust_level"] = "untrusted"
        manifest = MODULE.build_manifest(state, ["I-009"], created_at="2026-09-17T00:00:00Z")
        findings = MODULE.lint_manifest(state, manifest)
        self.assertIn("UNTRUSTED_CONTROL", {f.code for f in findings})


if __name__ == "__main__":
    unittest.main()
