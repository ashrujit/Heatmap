"""Offline transport contracts. All writable profiles are temporary directories."""
import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "skills/saavik/scripts"))
import kahnctl as ctl


def draft(*extra):
    args = ctl.parser().parse_args(["new-draft", "NQ", "--side", "long", "--arena", "400:600",
        "--probe", "400:410", "--target", "590:600", "--passive-harvest", "590:600",
        "--probe-qty", "2", "--add-qty", "2", "--max-qty", "10", "--scale-mode", "scale_allowed",
        "--dry-run", *extra])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        args.func(args)
    return json.loads(output.getvalue())["campaign"]


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.profile = (REPO / ".tmp/kahn-transport-tests" / uuid4().hex).resolve()
        self.profile.mkdir(parents=True)
        self.addCleanup(self.clean_profile)
        self.checkpoint = {**{key: str(value) for key, value in ctl.expected_runtime_paths(self.profile).items()},
            "version": 2, "updated_utc": ctl.iso_utc(ctl.utc_now()), "runtime_state": "Running",
            "campaign_id": "test", "campaign_digest": "digest", "runtime_instance_id": "instance",
            "execution_attempt_count": 0, "position_quantity": 0, "simulated_position_quantity": 0,
            "phase": "Ready", "authorization_state": "WATCH", "bound_working_order_count": 0}

    def clean_profile(self):
        assert self.profile.is_relative_to((REPO / ".tmp/kahn-transport-tests").resolve())
        for path in self.profile.iterdir():
            path.unlink()
        self.profile.rmdir()

    def test_two_box_assembler(self):
        result = draft()
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual([w["role"] for w in result["waypoints"]], ["trap_probe", "target"])

    def test_root_only(self):
        result = draft("--scale-mode", "root_only", "--max-qty", "2")
        self.assertEqual(result["sizing"]["max_position_quantity"], 2)

    def test_press_is_not_silently_ignored(self):
        with self.assertRaises(ctl.KahnctlError): draft("--press", "420:450")

    def test_no_add_is_not_silently_ignored(self):
        with self.assertRaises(ctl.KahnctlError): draft("--no-add", "400:410")

    def test_legacy_still_valid_for_audit(self):
        result = draft(); result["schema_version"] = 1
        self.assertEqual(ctl.validate_campaign(result, allow_stale=True)["load_state"], "LEGACY/AUDIT")

    def test_conversion_requires_each_removed_id(self):
        result = draft(); result["schema_version"] = 1
        result["waypoints"].append({"id": "old-press", "role": "press", "range": {"lower": 420, "upper": 450}})
        with self.assertRaises(ctl.KahnctlError): ctl.convert_campaign(result, [], False)
        converted, report = ctl.convert_campaign(result, ["old-press"], True)
        self.assertEqual(report["removed_constraints"][0]["id"], "old-press")
        self.assertEqual(converted["window"], result["window"])
        self.assertEqual(result["schema_version"], 1)

    def test_unknown_conversion_constraint(self):
        result = draft(); result["schema_version"] = 1
        with self.assertRaises(ctl.KahnctlError): ctl.convert_campaign(result, ["unknown"], False)

    def test_scoped_go_live(self):
        command = ctl.scoped_control("GO_LIVE", None, self.profile, self.checkpoint)
        self.assertEqual([command[k] for k in ("schema_version", "campaign_id", "campaign_digest", "runtime_instance_id", "attempt")],
                         [2, "test", "digest", "instance", 0])

    def test_stale_checkpoint(self):
        self.checkpoint["updated_utc"] = "2000-01-01T00:00:00Z"
        with self.assertRaises(ctl.KahnctlError): ctl.scoped_control("GO_LIVE", None, self.profile, self.checkpoint)

    def test_path_mismatch(self):
        self.checkpoint["campaign_path"] = "other/campaign.json"
        with self.assertRaises(ctl.KahnctlError): ctl.scoped_control("GO_LIVE", None, self.profile, self.checkpoint)

    def test_be_flat_rejected(self):
        with self.assertRaises(ctl.KahnctlError): ctl.scoped_control("BE", None, self.profile, self.checkpoint)

    def test_be_attempt_bound(self):
        self.checkpoint.update(position_quantity=2, simulated_position_quantity=2, execution_attempt_count=3)
        self.assertEqual(ctl.scoped_control("BE", None, self.profile, self.checkpoint)["attempt"], 3)

    def test_unresolved_order_rejects_control(self):
        self.checkpoint["unresolved_risk_order"] = "pending"
        with self.assertRaises(ctl.KahnctlError): ctl.scoped_control("GO_LIVE", None, self.profile, self.checkpoint)

    def test_legacy_runtime_rejects_new_controls(self):
        self.checkpoint["version"] = 1
        with self.assertRaises(ctl.KahnctlError): ctl.scoped_control("GO_LIVE", None, self.profile, self.checkpoint)

    def test_paused_control(self):
        self.checkpoint["phase"] = "Paused"
        with self.assertRaises(ctl.KahnctlError): ctl.scoped_control("GO_LIVE", None, self.profile, self.checkpoint)

    def test_dry_control_writes_nothing(self):
        ctl.atomic_write(self.profile / "checkpoint.json", self.checkpoint)
        args = ctl.parser().parse_args(["go-live", "--runtime-dir", str(self.profile), "--dry-run"])
        with contextlib.redirect_stdout(io.StringIO()): args.func(args)
        self.assertFalse((self.profile / "control.json").exists())

    def test_dispatch_requires_checkpoint(self):
        with self.assertRaises(ctl.KahnctlError): ctl.prepare_campaign_dispatch(self.profile, draft(), argparse.Namespace())

    def test_first_dispatch_accepts_actual_runtime_checkpoint_writer(self):
        subprocess.run([str(Path.home() / "AppData/Local/Microsoft/dotnet/dotnet.exe"),
            str(REPO / "KahnRuntime.Tests/bin/Release/net10.0/KahnRuntime.Tests.dll"),
            "write-checkpoint", str(self.profile)], check=True, capture_output=True, text=True)
        saved = ctl.read_checkpoint_if_present(self.profile)
        self.assertEqual(saved["version"], 2)
        self.assertIsNone(saved["campaign_id"])
        self.assertIsNone(ctl.prepare_campaign_dispatch(self.profile, draft(), argparse.Namespace()))
        self.assertFalse((self.profile / "campaign.json").exists())
        self.assertFalse((self.profile / "control.json").exists())

    def test_dispatch_still_rejects_legacy_checkpoint(self):
        self.checkpoint.update(version=1, campaign_id=None)
        ctl.atomic_write(self.profile / "checkpoint.json", self.checkpoint)
        with self.assertRaises(ctl.KahnctlError):
            ctl.prepare_campaign_dispatch(self.profile, draft(), argparse.Namespace())

    def test_dispatch_requires_flat(self):
        self.checkpoint["position_quantity"] = 1
        ctl.atomic_write(self.profile / "checkpoint.json", self.checkpoint)
        with self.assertRaises(ctl.KahnctlError): ctl.prepare_campaign_dispatch(self.profile, draft(), argparse.Namespace())

    def test_dispatch_rejects_unknown_order_even_retired(self):
        self.checkpoint.update(phase="Retired", unresolved_risk_order="pending")
        ctl.atomic_write(self.profile / "checkpoint.json", self.checkpoint)
        with self.assertRaises(ctl.KahnctlError): ctl.prepare_campaign_dispatch(self.profile, draft(), argparse.Namespace())

    def test_legacy_dispatch_rejected(self):
        result = draft(); result["schema_version"] = 1
        with self.assertRaises(ctl.KahnctlError): ctl.prepare_campaign_dispatch(self.profile, result, argparse.Namespace(dry_run=True))

    def test_6j_profile_preserved(self):
        self.assertEqual(ctl.DEFAULT_PROFILES["6J"].name, "6J")

    def test_runtime_parser_accepts_actual_assembler_output(self):
        path = self.profile / "draft.json"
        ctl.atomic_write(path, draft())
        result = subprocess.run([str(Path.home() / "AppData/Local/Microsoft/dotnet/dotnet.exe"),
            str(REPO / "KahnRuntime.Tests/bin/Release/net10.0/KahnRuntime.Tests.dll"), "validate-plan", str(path)],
            check=True, capture_output=True, text=True)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed, {"schema": 2, "roles": ["TrapProbe", "Target"], "authorized": False})


if __name__ == "__main__": unittest.main()
