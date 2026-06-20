import argparse
import json
from pathlib import Path
import tempfile
import unittest

import earctl


class EarctlTests(unittest.TestCase):
    def valid_directive(self):
        now = earctl.now_et()
        return {
            "schema_version": 1,
            "kind": "TRADE_DIRECTIVE",
            "id": "test-short-01",
            "status": "active",
            "created_at": earctl.timestamp(now),
            "side": "short",
            "window": {
                "not_before": earctl.timestamp(now),
                "expires_at": earctl.timestamp(now + earctl.timedelta(minutes=30)),
            },
            "entry": {
                "mode": "contest_transition",
                "order_price_range": {"lower": 30475, "upper": 30550},
                "context_price_range": {"lower": 30380, "upper": 30550},
                "add_price_range": {"lower": 30380, "upper": 30550},
                "pre_entry_invalidation": {"direction": "above", "price": 30560},
                "allowed_resolutions": ["direct_conversion", "supported_reclaim"],
            },
            "sizing": {
                "base_quantity": 2,
                "add_quantity": 1,
                "max_position_quantity": 5,
                "adds_allowed": True,
            },
            "retries": {"max_base_reentries": 3},
            "stop": {
                "base": "reverse_entry_resolution",
                "leveraged": "weighted_breakeven",
                "opposite_failure_object": "flatten",
            },
            "target": {
                "mode": "HARD_TP",
                "price": 30380,
                "direction": "below",
                "reference": "rail",
            },
        }

    def test_validate_and_atomic_dispatch(self):
        directive = self.valid_directive()
        earctl.validate_directive(directive, 5)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = earctl.dispatch_payload(directive, root, 5, 0)
            self.assertEqual("pending", result["outcome"])
            self.assertEqual(directive, json.loads((root / "directive.json").read_text()))

    def test_rejects_unknown_and_scaling_mismatch(self):
        directive = self.valid_directive()
        directive["unknown"] = True
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)
        directive = self.valid_directive()
        directive["sizing"]["adds_allowed"] = False
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)

    def test_control_and_status(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = argparse.Namespace(
                runtime_dir=root,
                action="FLAT",
                directive_id=None,
                id="flat-test-01",
                reason="test",
                wait_seconds=0,
                dry_run=False,
            )
            result = earctl.command_control(args)
            self.assertEqual("pending", result["outcome"])
            checkpoint = {"version": 1, "runtime_state": "Armed"}
            (root / "checkpoint.json").write_text(json.dumps(checkpoint))
            (root / "events.jsonl").write_text(json.dumps({
                "event": "runtime_started",
                "trading_enabled": False,
            }) + "\n")
            status = earctl.status_snapshot(root)
            self.assertEqual("Armed", status["checkpoint"]["runtime_state"])
            self.assertTrue(status["runtime_running"])

    def test_reissue_uses_fresh_identity_and_window(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            original = self.valid_directive()
            original["created_at"] = "2026-06-19T10:00:00-04:00"
            original["window"] = {
                "not_before": "2026-06-19T10:00:00-04:00",
                "expires_at": "2026-06-19T10:30:00-04:00",
            }
            earctl.atomic_write(root / "directive.json", original)
            args = argparse.Namespace(
                runtime_dir=root,
                source=None,
                ttl_minutes=60,
                id="test-short-reissue-02",
                reason="strategy remains valid",
                wait_seconds=0,
                dry_run=True,
                instance_max_quantity=5,
            )
            result = earctl.command_reissue(args)
            reissued = result["directive"]
            self.assertEqual("validated", result["outcome"])
            self.assertEqual("test-short-reissue-02", reissued["id"])
            self.assertNotEqual(original["created_at"], reissued["created_at"])
            start = earctl._timestamp(reissued["window"]["not_before"], "start")
            end = earctl._timestamp(reissued["window"]["expires_at"], "end")
            self.assertEqual(60 * 60, (end - start).total_seconds())


if __name__ == "__main__":
    unittest.main()
