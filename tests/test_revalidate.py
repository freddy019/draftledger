import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("revalidate", ROOT / "scripts" / "revalidate.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RevalidationTests(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))

    def test_plan_resolves_lineage_but_keeps_semantic_review(self):
        state = self.load("review-state.json")
        plan = MODULE.build_plan(state)
        self.assertEqual(1, plan["decision_count"])
        entry = plan["entries"][0]
        self.assertEqual("D-001", entry["decision_id"])
        migrations = {(m["from"], m["to"]) for m in entry["candidate_migrations"]}
        self.assertIn(("F-001", "F-002"), migrations)
        self.assertIn(("I-001", "I-002"), migrations)
        self.assertIn("A-001", entry["blockers"])
        self.assertTrue(entry["semantic_review_required"])

    def test_supersede_creates_new_decision_and_history(self):
        state = self.load("review-state.json")
        resolution = self.load("revalidation-resolution.json")
        out = MODULE.apply_resolutions(state, resolution, timestamp="2026-09-17T00:00:00Z")
        decisions = {d["id"]: d for d in out["decisions"]}
        self.assertEqual("superseded", decisions["D-001"]["status"])
        self.assertEqual("D-002", decisions["D-001"]["superseded_by"])
        self.assertEqual("active", decisions["D-002"]["status"])
        self.assertEqual(["F-002"], decisions["D-002"]["facts_used"])
        history = decisions["D-001"]["validation_history"][-1]
        self.assertEqual("superseded", history["outcome"])
        self.assertEqual("D-002", history["replacement_decision_id"])

    def test_revalidation_rejects_stale_dependencies(self):
        state = self.load("review-state.json")
        resolution = {
            "version": "1.0",
            "resolutions": [{
                "decision_id": "D-001",
                "outcome": "revalidated",
                "rationale": "Pretend it still holds without updating dependencies."
            }]
        }
        with self.assertRaises(ValueError):
            MODULE.apply_resolutions(state, resolution, timestamp="2026-09-17T00:00:00Z")

    def test_blocked_creates_open_item(self):
        state = self.load("review-state.json")
        resolution = {
            "version": "1.0",
            "resolutions": [{
                "decision_id": "D-001",
                "outcome": "blocked",
                "rationale": "Refund-rate evidence is missing."
            }]
        }
        out = MODULE.apply_resolutions(state, resolution, timestamp="2026-09-17T00:00:00Z")
        decision = {d["id"]: d for d in out["decisions"]}["D-001"]
        self.assertEqual("needs_review", decision["status"])
        self.assertTrue(any(o.get("related_decision") == "D-001" for o in out["open_items"]))
        self.assertEqual("blocked", decision["validation_history"][-1]["outcome"])


if __name__ == "__main__":
    unittest.main()
