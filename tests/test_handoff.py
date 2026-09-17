from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SPEC = importlib.util.spec_from_file_location("handoff", SCRIPTS / "handoff.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

T0 = "2026-09-17T00:00:00Z"
T1 = "2026-09-17T00:01:00Z"
T2 = "2026-09-17T00:02:00Z"
T3 = "2026-09-17T00:03:00Z"


class HandoffTests(unittest.TestCase):
    def board(self):
        return MODULE.create_board(
            handoff_id="H-test", project_name="test", objective="parallel work", created_at=T0
        )

    def ready_board(self):
        board = self.board()
        MODULE.add_work(
            board, work_id="W-one", title="One", objective="Do one",
            dependencies=[], scope=["src/one.py"], acceptance=["passes"], inputs=[], at=T1,
        )
        MODULE.register_agent(board, agent_id="agent-a", thread_ref="thread-a", at=T1)
        MODULE.register_agent(board, agent_id="agent-b", thread_ref="thread-b", at=T1)
        return board

    def test_claim_complete_and_dependency_gate(self):
        board = self.ready_board()
        MODULE.add_work(
            board, work_id="W-two", title="Two", objective="Integrate",
            dependencies=["W-one"], scope=["integration"], acceptance=["integrated"], inputs=[], at=T1,
        )
        with self.assertRaises(MODULE.HandoffError):
            MODULE.claim_work(board, work_id="W-two", agent_id="agent-b", lease_minutes=60,
                              take_over_expired=False, at=T2)
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-a", lease_minutes=60,
                          take_over_expired=False, at=T2)
        MODULE.complete_work(board, work_id="W-one", agent_id="agent-a", summary="done",
                             outputs=["out.txt"], at=T3)
        MODULE.claim_work(board, work_id="W-two", agent_id="agent-b", lease_minutes=60,
                          take_over_expired=False, at=T3)
        self.assertEqual(MODULE.work_map(board)["W-two"]["owner"], "agent-b")

    def test_wrong_owner_cannot_update_or_complete(self):
        board = self.ready_board()
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-a", lease_minutes=60,
                          take_over_expired=False, at=T2)
        with self.assertRaises(MODULE.HandoffError):
            MODULE.add_progress(board, work_id="W-one", agent_id="agent-b", message="mine",
                                artifacts=[], at=T3)
        with self.assertRaises(MODULE.HandoffError):
            MODULE.complete_work(board, work_id="W-one", agent_id="agent-b", summary="mine",
                                 outputs=[], at=T3)

    def test_overlapping_active_scopes_are_rejected(self):
        board = self.ready_board()
        MODULE.add_work(
            board, work_id="W-two", title="Two", objective="Touch child path",
            dependencies=[], scope=["src/one.py/tests"], acceptance=["passes"], inputs=[], at=T1,
        )
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-a", lease_minutes=60,
                          take_over_expired=False, at=T2)
        with self.assertRaises(MODULE.HandoffError):
            MODULE.claim_work(board, work_id="W-two", agent_id="agent-b", lease_minutes=60,
                              take_over_expired=False, at=T2)
        MODULE.work_map(board)["W-two"].update({"status": "claimed", "owner": "agent-b", "lease_expires_at": T3})
        self.assertIn("SCOPE_COLLISION", {row["code"] for row in MODULE.lint_board(board)})

    def test_expired_claim_takeover_is_explicit_and_audited(self):
        board = self.ready_board()
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-a", lease_minutes=1,
                          take_over_expired=False, at=T1)
        with self.assertRaises(MODULE.HandoffError):
            MODULE.claim_work(board, work_id="W-one", agent_id="agent-b", lease_minutes=60,
                              take_over_expired=False, at=T3)
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-b", lease_minutes=60,
                          take_over_expired=True, at=T3)
        self.assertEqual(MODULE.work_map(board)["W-one"]["owner"], "agent-b")
        self.assertEqual(board["events"][-1]["type"], "expired_claim_taken_over")
        self.assertEqual(board["events"][-1]["details"]["previous_owner"], "agent-a")

    def test_block_requires_resolution_before_reclaim(self):
        board = self.ready_board()
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-a", lease_minutes=60,
                          take_over_expired=False, at=T1)
        MODULE.block_work(board, work_id="W-one", agent_id="agent-a", reason="missing input", at=T2)
        with self.assertRaises(MODULE.HandoffError):
            MODULE.claim_work(board, work_id="W-one", agent_id="agent-b", lease_minutes=60,
                              take_over_expired=True, at=T3)
        MODULE.resume_work(board, work_id="W-one", agent_id="agent-a", resolution="input supplied",
                           take_over=False, at=T3)
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-b", lease_minutes=60,
                          take_over_expired=False, at=T3)
        blocker = MODULE.work_map(board)["W-one"]["blockers"][0]
        self.assertEqual(blocker["status"], "resolved")

    def test_blocked_work_can_be_explicitly_taken_over(self):
        board = self.ready_board()
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-a", lease_minutes=60,
                          take_over_expired=False, at=T1)
        MODULE.block_work(board, work_id="W-one", agent_id="agent-a", reason="owner unavailable", at=T2)
        with self.assertRaises(MODULE.HandoffError):
            MODULE.resume_work(board, work_id="W-one", agent_id="agent-b", resolution="reassigned",
                               take_over=False, at=T3)
        MODULE.resume_work(board, work_id="W-one", agent_id="agent-b", resolution="reassigned",
                           take_over=True, at=T3)
        self.assertEqual(board["events"][-1]["type"], "blocked_work_taken_over")
        self.assertIsNone(MODULE.work_map(board)["W-one"]["owner"])

    def test_cancel_preserves_owner_and_rejects_completed_work(self):
        board = self.ready_board()
        MODULE.cancel_work(board, work_id="W-one", agent_id="agent-b", reason="scope removed", at=T2)
        self.assertEqual(MODULE.work_map(board)["W-one"]["status"], "cancelled")
        board = self.ready_board()
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-a", lease_minutes=60,
                          take_over_expired=False, at=T1)
        MODULE.complete_work(board, work_id="W-one", agent_id="agent-a", summary="done", outputs=[], at=T2)
        with self.assertRaises(MODULE.HandoffError):
            MODULE.cancel_work(board, work_id="W-one", agent_id="agent-a", reason="too late", at=T3)

    def test_stale_revision_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "handoff.json"
            MODULE.atomic_write_json(path, self.ready_board())
            before = path.read_bytes()
            with self.assertRaises(MODULE.HandoffError):
                MODULE.mutate(path, expected_revision=7, at=T2, operation=lambda board: None)
            self.assertEqual(path.read_bytes(), before)

    def test_operation_time_cannot_go_backwards(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "handoff.json"
            board = self.ready_board()
            board["updated_at"] = T2
            MODULE.atomic_write_json(path, board)
            with self.assertRaises(MODULE.HandoffError):
                MODULE.mutate(path, expected_revision=None, at=T1, operation=lambda value: None)

    def test_refresh_state_is_blocked_during_active_work(self):
        board = self.ready_board()
        MODULE.claim_work(board, work_id="W-one", agent_id="agent-a", lease_minutes=60,
                          take_over_expired=False, at=T1)
        with self.assertRaises(MODULE.HandoffError):
            MODULE.refresh_state(board, state_path=ROOT / "examples/sample-state.json", actor="coordinator", at=T2)

    def test_lint_detects_cycle_unknown_owner_and_stale_state(self):
        board = self.ready_board()
        item = MODULE.work_map(board)["W-one"]
        item["depends_on"] = ["W-one"]
        item["owner"] = "ghost"
        state = json.loads((ROOT / "examples/sample-state.json").read_text(encoding="utf-8"))
        board["base_state"] = {"path": "state.json", "fingerprint": "sha256:" + "0" * 64}
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            findings = MODULE.lint_board(board, state_path=state_path)
        codes = {row["code"] for row in findings}
        self.assertTrue({"SELF_DEPENDENCY", "DEPENDENCY_CYCLE", "UNKNOWN_OWNER", "STALE_BASE_STATE"} <= codes)

    def test_concurrent_cli_claims_have_one_winner(self):
        with tempfile.TemporaryDirectory() as td:
            board_path = Path(td) / "handoff.json"
            board = self.ready_board()
            MODULE.atomic_write_json(board_path, board)
            base = [sys.executable, str(SCRIPTS / "handoff.py"), "--board", str(board_path), "claim", "W-one"]
            p1 = subprocess.Popen(base + ["--agent", "agent-a", "--at", T2], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            p2 = subprocess.Popen(base + ["--agent", "agent-b", "--at", T2], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            out1, err1 = p1.communicate(timeout=10)
            out2, err2 = p2.communicate(timeout=10)
            self.assertEqual(sorted([p1.returncode, p2.returncode]), [0, 2], (out1, err1, out2, err2))
            final = MODULE.load_board(board_path)
            self.assertIn(MODULE.work_map(final)["W-one"]["owner"], {"agent-a", "agent-b"})
            self.assertEqual(final["revision"], 1)

    def test_template_and_example_lint_clean(self):
        for rel in ("templates/handoff.json", "examples/handoff-board.json"):
            board = MODULE.load_board(ROOT / rel)
            self.assertEqual(MODULE.lint_board(board), [], rel)


if __name__ == "__main__":
    unittest.main()
