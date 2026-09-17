import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("state_diff", ROOT / "scripts" / "state_diff.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class StateDiffTests(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))

    def test_material_changes_trigger_revalidation(self):
        old = self.load("diff-before.json")
        new = self.load("diff-after.json")
        changes = MODULE.compute_changes(old, new)
        reviews = MODULE.dependency_revalidation(old, new, changes)

        changed_ids = {c.item_id for c in changes}
        self.assertTrue({"F-001", "F-002", "A-001", "I-001", "I-002"}.issubset(changed_ids))
        self.assertEqual(["D-001"], [r.decision_id for r in reviews])
        self.assertEqual({"F-001", "A-001", "I-001"}, set(reviews[0].triggers))

    def test_annotate_marks_decision_needs_review(self):
        old = self.load("diff-before.json")
        new = self.load("diff-after.json")
        changes = MODULE.compute_changes(old, new)
        reviews = MODULE.dependency_revalidation(old, new, changes)
        annotated = MODULE.annotate_review_state(new, reviews)
        decision = annotated["decisions"][0]
        self.assertEqual("needs_review", decision["status"])
        self.assertIn("F-001", decision["review_triggered_by"])
        self.assertTrue(decision["review_reason"])

    def test_unrelated_addition_does_not_invalidate_decision(self):
        old = self.load("diff-before.json")
        new = json.loads(json.dumps(old))
        new["facts"].append({
            "id": "F-099",
            "statement": "Unrelated fact.",
            "source": "user-confirmed",
            "scope": "other",
            "status": "active"
        })
        changes = MODULE.compute_changes(old, new)
        reviews = MODULE.dependency_revalidation(old, new, changes)
        self.assertEqual([], reviews)


if __name__ == "__main__":
    unittest.main()
