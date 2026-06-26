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
                "leveraged": "current_sponsor_failure",
                "opposite_failure_object": "flatten",
            },
            "target": {
                "mode": "HARD_TP",
                "price": 30380,
                "direction": "below",
                "reference": "rail",
            },
        }

    def checkpoint(self, directive=None, state="Idle", **overrides):
        value = {
            "version": 1,
            "updated_utc": earctl.timestamp(earctl.datetime.now(earctl.timezone.utc)),
            "runtime_state": state,
            "last_directive_id": None if directive is None else directive["id"],
            "last_directive_json": None if directive is None else json.dumps(directive),
            "trading_enabled": False,
            "execution_symbol": "MNQU6",
            "market_data_symbol": "NQU6",
            "instance_max_quantity": 5,
            "worker_poll_ms": 250,
            "evidence_state": "Ready",
            "evidence_epoch_reason": "startup",
            "evidence_epoch_started_utc": earctl.timestamp(
                earctl.datetime.now(earctl.timezone.utc) - earctl.timedelta(seconds=30)),
            "evidence_sample_count": 31,
            "evidence_warmup_seconds": 30,
            "evidence_warmup_required_samples": 30,
            "evidence_warmup_remaining_seconds": 0,
            "recovery_action_required": False,
            "bound_working_order_count": 0,
            "unresolved_entry_count": 0,
            "position_quantity": 0,
            "position_average_price": 0,
        }
        value.update(overrides)
        return value

    def test_validate_and_atomic_dispatch(self):
        directive = self.valid_directive()
        earctl.validate_directive(directive, 5)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = earctl.dispatch_payload(directive, root, 5, 0)
            self.assertEqual("pending", result["outcome"])
            self.assertEqual(directive, json.loads((root / "directive.json").read_text()))

    def test_context_defaults_without_becoming_conversational_input(self):
        args = earctl.parser().parse_args([
            "dispatch",
            "--side", "short",
            "--order-range", "30475", "30550",
            "--add-range", "30380", "30550",
            "--base-quantity", "2",
            "--add-quantity", "1",
            "--max-position", "5",
            "--target-price", "30380",
            "--dry-run",
        ])
        directive = earctl.build_directive(args)
        self.assertEqual(
            {"lower": 30380.0, "upper": 30550.0},
            directive["entry"]["context_price_range"],
        )

        args = earctl.parser().parse_args([
            "dispatch",
            "--side", "short",
            "--order-range", "30475", "30550",
            "--base-quantity", "2",
            "--add-quantity", "0",
            "--max-position", "2",
            "--no-adds",
            "--target-price", "30380",
            "--dry-run",
        ])
        directive = earctl.build_directive(args)
        earctl.validate_directive(directive, 5)
        self.assertEqual(
            {"lower": 30475.0, "upper": 30550.0},
            directive["entry"]["context_price_range"],
        )

    def test_add_range_defaults_to_campaign_envelope(self):
        short_args = earctl.parser().parse_args([
            "dispatch",
            "--side", "short",
            "--order-range", "30475", "30550",
            "--base-quantity", "2",
            "--add-quantity", "1",
            "--max-position", "5",
            "--target-price", "29800",
            "--dry-run",
        ])
        short = earctl.build_directive(short_args)
        earctl.validate_directive(short, 5)
        self.assertEqual(
            {"lower": 29800.0, "upper": 30550.0},
            short["entry"]["add_price_range"],
        )
        self.assertEqual(short["entry"]["add_price_range"],
                         short["entry"]["context_price_range"])

        long_args = earctl.parser().parse_args([
            "dispatch",
            "--side", "long",
            "--order-range", "30475", "30550",
            "--base-quantity", "2",
            "--add-quantity", "1",
            "--max-position", "5",
            "--target-price", "30800",
            "--dry-run",
        ])
        long = earctl.build_directive(long_args)
        earctl.validate_directive(long, 5)
        self.assertEqual(
            {"lower": 30475.0, "upper": 30800.0},
            long["entry"]["add_price_range"],
        )
        self.assertEqual(long["entry"]["add_price_range"],
                         long["entry"]["context_price_range"])

    def test_rejects_unknown_and_scaling_mismatch(self):
        directive = self.valid_directive()
        directive["unknown"] = True
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)
        directive = self.valid_directive()
        directive["sizing"]["adds_allowed"] = False
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)
        directive = self.valid_directive()
        directive["sizing"]["max_position_quantity"] = 2
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)
        directive = self.valid_directive()
        directive["sizing"]["adds_allowed"] = False
        directive["sizing"]["add_quantity"] = 0
        directive["entry"]["add_price_range"] = None
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)
        directive = self.valid_directive()
        directive["entry"]["add_price_range"]["lower"] = 30300
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)

    def test_rejects_legacy_target_modes(self):
        for mode in (
            "TARGET_DECISION",
            "TRAIL_AFTER_TARGET",
            "TARGET_DECISION_BEFORE_EXTREME",
        ):
            with self.subTest(mode=mode):
                directive = self.valid_directive()
                directive["target"]["mode"] = mode
                with self.assertRaises(earctl.ContractError):
                    earctl.validate_directive(directive, 5)

    def test_lineage_validation_and_dispatch_shape(self):
        directive = self.valid_directive()
        directive["lineage"] = {
            "mode": "CONTINUE",
            "parent_directive_id": "parent-short-01",
        }
        earctl.validate_directive(directive, 5)

        directive = self.valid_directive()
        directive["lineage"] = {"mode": "CONTINUE"}
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)

        directive = self.valid_directive()
        directive["lineage"] = {
            "mode": "NEW",
            "parent_directive_id": "parent-short-01",
        }
        with self.assertRaises(earctl.ContractError):
            earctl.validate_directive(directive, 5)

        args = earctl.parser().parse_args([
            "dispatch",
            "--side", "short",
            "--order-range", "30475", "30550",
            "--base-quantity", "2",
            "--add-quantity", "1",
            "--max-position", "5",
            "--target-price", "30380",
            "--lineage-mode", "CONTINUE",
            "--parent-directive-id", "parent-short-01",
            "--dry-run",
        ])
        built = earctl.build_directive(args)
        self.assertEqual(
            {"mode": "CONTINUE", "parent_directive_id": "parent-short-01"},
            built["lineage"],
        )
        earctl.validate_directive(built, 5)

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
            checkpoint = self.checkpoint(state="Idle")
            (root / "checkpoint.json").write_text(json.dumps(checkpoint))
            events = [json.dumps({
                "event": "runtime_started",
                "trading_enabled": False,
            })]
            events.extend(json.dumps({"event": "evidence_transition", "sequence": i})
                          for i in range(600))
            events.append(json.dumps({"event": "entry_order_unresolved"}))
            (root / "events.jsonl").write_text("\n".join(events) + "\n")
            status = earctl.status_snapshot(root)
            self.assertEqual("Idle", status["runtime"]["state"])
            self.assertEqual("running", status["runtime"]["health"])
            self.assertEqual("SHADOW", status["runtime"]["mode"])
            self.assertEqual("MNQU6", status["runtime"]["execution_symbol"])
            self.assertEqual("NQU6", status["runtime"]["market_data_symbol"])
            self.assertEqual("Ready", status["evidence"]["state"])
            self.assertEqual(31, status["evidence"]["sample_count"])
            self.assertEqual("entry_order_unresolved",
                             status["recent_errors"][0]["event"])

    def test_reissue_uses_fresh_identity_and_window(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            original = self.valid_directive()
            original["created_at"] = "2026-06-19T10:00:00-04:00"
            original["window"] = {
                "not_before": "2026-06-19T10:00:00-04:00",
                "expires_at": "2026-06-19T10:30:00-04:00",
            }
            rejected_file = self.valid_directive()
            rejected_file["id"] = "rejected-file-must-not-be-reissued"
            earctl.atomic_write(root / "directive.json", rejected_file)
            earctl.atomic_write(root / "checkpoint.json", self.checkpoint(original))
            status = earctl.status_snapshot(root)
            self.assertEqual("checkpoint_runtime_state",
                             status["directive"]["last_outcome"]["event"])
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
            self.assertNotEqual(rejected_file["id"], reissued["id"])
            self.assertEqual(original["entry"], reissued["entry"])
            self.assertNotIn("lineage", reissued)

    def test_continue_reissue_marks_parent_lineage(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            original = self.valid_directive()
            earctl.atomic_write(root / "checkpoint.json",
                                self.checkpoint(original, state="Armed"))
            (root / "events.jsonl").write_text(
                json.dumps({"event": "runtime_started"}) + "\n")
            args = argparse.Namespace(
                runtime_dir=root,
                source=None,
                ttl_minutes=30,
                id="test-short-continue-02",
                reason="same campaign after local protective exit",
                continue_lineage=True,
                wait_seconds=0,
                dry_run=False,
                instance_max_quantity=None,
            )
            result = earctl.command_reissue(args)
            continued = result["directive"]
            self.assertEqual("pending", result["outcome"])
            self.assertEqual("test-short-continue-02", continued["id"])
            self.assertEqual(
                {"mode": "CONTINUE", "parent_directive_id": original["id"]},
                continued["lineage"],
            )
            self.assertEqual(continued, json.loads((root / "directive.json").read_text()))

    def test_cancel_active_resolves_checkpoint_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            directive = self.valid_directive()
            earctl.atomic_write(root / "checkpoint.json",
                                self.checkpoint(directive, state="Armed"))
            args = argparse.Namespace(
                runtime_dir=root,
                id="cancel-active-test",
                reason="test",
                wait_seconds=0,
                dry_run=True,
            )
            result = earctl.command_cancel_active(args)
            self.assertEqual("validated", result["outcome"])
            self.assertEqual(directive["id"], result["control"]["directive_id"])

    def test_paused_directive_remains_active(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            directive = self.valid_directive()
            earctl.atomic_write(root / "checkpoint.json",
                                self.checkpoint(directive, state="Paused"))
            status = earctl.status_snapshot(root)
            self.assertEqual(directive["id"], status["directive"]["active_id"])

    def test_reissue_refuses_active_runtime_state(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            directive = self.valid_directive()
            earctl.atomic_write(root / "checkpoint.json",
                                self.checkpoint(directive, state="Armed"))
            (root / "events.jsonl").write_text(
                json.dumps({"event": "runtime_started"}) + "\n")
            args = argparse.Namespace(
                runtime_dir=root,
                source=None,
                ttl_minutes=30,
                id=None,
                reason=None,
                wait_seconds=0,
                dry_run=False,
                instance_max_quantity=None,
            )
            with self.assertRaisesRegex(earctl.ContractError, "prior_directive_active"):
                earctl.command_reissue(args)
            self.assertFalse((root / "directive.json").exists())

    def test_checkpoint_ceiling_replaces_client_default(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            earctl.atomic_write(root / "checkpoint.json",
                                self.checkpoint(instance_max_quantity=4))
            self.assertEqual(4, earctl.runtime_instance_ceiling(root, None))
            with self.assertRaises(earctl.ContractError):
                earctl.validate_directive(self.valid_directive(), 4)


if __name__ == "__main__":
    unittest.main()
