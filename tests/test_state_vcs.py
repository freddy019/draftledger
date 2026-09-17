import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("state_vcs", ROOT / "scripts" / "state_vcs.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class StateVCSTests(unittest.TestCase):
    def load(self, name="sample-state.json"):
        return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))

    def test_init_branch_switch_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "vcs"
            state = self.load()
            c1 = MODULE.init_repo(repo, state, created_at="2026-09-17T00:00:00Z")
            self.assertTrue(c1.startswith("C-"))

            MODULE.create_branch(repo, "experiment")
            exp = MODULE.switch_branch(repo, "experiment")
            exp["project"]["phase"] = "experiment"
            c2 = MODULE.checkpoint_state(
                repo, exp, message="experiment phase", created_at="2026-09-17T00:01:00Z"
            )
            self.assertNotEqual(c1, c2)

            restored_main = MODULE.switch_branch(repo, "main")
            self.assertEqual("testing", restored_main["project"]["phase"])
            meta = MODULE.load_meta(repo)
            self.assertEqual(c1, meta["branches"]["main"])
            self.assertEqual(c2, meta["branches"]["experiment"])

    def test_rollback_is_append_only(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "vcs"
            state1 = self.load()
            c1 = MODULE.init_repo(repo, state1, created_at="2026-09-17T00:00:00Z")
            state2 = copy.deepcopy(state1)
            state2["project"]["phase"] = "phase-2"
            c2 = MODULE.checkpoint_state(
                repo, state2, message="phase 2", created_at="2026-09-17T00:01:00Z"
            )
            c3, restored = MODULE.rollback_to(
                repo, c1, created_at="2026-09-17T00:02:00Z"
            )
            self.assertNotEqual(c2, c3)
            self.assertEqual(state1, restored)
            rollback_record = MODULE.load_checkpoint(repo, c3)
            self.assertEqual([c2], rollback_record["parents"])
            self.assertEqual(c1, rollback_record["operation"]["target"])
            # Old history still exists.
            self.assertEqual(c2, MODULE.load_checkpoint(repo, c2)["id"])

    def test_three_way_merge_non_conflicting_fields(self):
        base = self.load()
        ours = copy.deepcopy(base)
        theirs = copy.deepcopy(base)
        ours["project"]["phase"] = "main-work"
        theirs["project"]["objective"] = "Alternative objective"
        merged, conflicts = MODULE.merge_states(base, ours, theirs)
        self.assertEqual([], conflicts)
        self.assertEqual("main-work", merged["project"]["phase"])
        self.assertEqual("Alternative objective", merged["project"]["objective"])

    def test_three_way_merge_reports_same_field_conflict(self):
        base = self.load()
        ours = copy.deepcopy(base)
        theirs = copy.deepcopy(base)
        ours["facts"][0]["statement"] = "Price is 158."
        theirs["facts"][0]["statement"] = "Price is 178."
        _, conflicts = MODULE.merge_states(base, ours, theirs)
        paths = {c["path"] for c in conflicts}
        self.assertIn("facts/F-001/statement", paths)

    def test_merge_marks_decision_for_revalidation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "vcs"
            base = self.load()
            MODULE.init_repo(repo, base, created_at="2026-09-17T00:00:00Z")
            MODULE.create_branch(repo, "experiment")
            exp = MODULE.switch_branch(repo, "experiment")

            # Replace a fact on the experiment branch without touching the old
            # decision. Merge should refuse to trust D-001 silently.
            exp["facts"][0]["status"] = "superseded"
            exp["facts"][0]["superseded_by"] = "F-002"
            exp["facts"].append({
                "id": "F-002",
                "statement": "The current normal selling price is 158.",
                "source": "user-confirmed",
                "scope": "project",
                "status": "active",
                "last_confirmed": "2026-09-17",
            })
            MODULE.checkpoint_state(
                repo, exp, message="test alternate price", created_at="2026-09-17T00:01:00Z"
            )

            MODULE.switch_branch(repo, "main")
            cid, merged, report = MODULE.merge_ref(
                repo, "experiment", created_at="2026-09-17T00:02:00Z"
            )
            self.assertIsNotNone(cid)
            self.assertEqual("merged", report["status"])
            self.assertIsNotNone(merged)
            decision = next(x for x in merged["decisions"] if x["id"] == "D-001")
            self.assertEqual("needs_review", decision["status"])
            self.assertIn("F-001", decision["review_triggered_by"])

    def test_ref_diff(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "vcs"
            state = self.load()
            MODULE.init_repo(repo, state, created_at="2026-09-17T00:00:00Z")
            MODULE.create_branch(repo, "alt")
            alt = MODULE.switch_branch(repo, "alt")
            alt["project"]["phase"] = "alt"
            MODULE.checkpoint_state(repo, alt, message="alt", created_at="2026-09-17T00:01:00Z")
            report = MODULE.diff_refs(repo, "main", "alt")
            # Project metadata is intentionally outside semantic state diff, so
            # add a governed fact and verify ref diff on a material registry.
            alt["facts"].append({
                "id": "F-099",
                "statement": "Alternative fact.",
                "source": "user-confirmed",
                "scope": "project",
                "status": "active",
            })
            MODULE.checkpoint_state(repo, alt, message="alt fact", created_at="2026-09-17T00:02:00Z")
            report = MODULE.diff_refs(repo, "main", "alt")
            self.assertIn("F-099", {x["item_id"] for x in report["changes"]})


if __name__ == "__main__":
    unittest.main()
