#!/usr/bin/env python3
"""Small transport helper for KahnRuntime operator controls."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_RUNTIME_DIR = Path.home() / "Documents" / "KahnRuntime"


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def build_control(action: str, reason: str | None) -> dict[str, Any]:
    created = datetime.now(timezone.utc)
    token = created.strftime("%Y%m%dT%H%M%S%fZ")
    return {
        "schema_version": 1,
        "kind": "KAHN_CONTROL",
        "id": f"kahn-{action.lower()}-{token}-{uuid4().hex[:8]}",
        "action": action.upper(),
        "reason": reason or "Operator control",
        "created_at": created.isoformat().replace("+00:00", "Z"),
    }


def runtime_dir_arg(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def command_control(args: argparse.Namespace) -> int:
    runtime_dir = runtime_dir_arg(args.runtime_dir)
    payload = build_control(args.action, args.reason)
    path = runtime_dir / "control.json"
    atomic_write(path, payload)
    print(json.dumps({
        "ok": True,
        "runtime_dir": str(runtime_dir),
        "control_path": str(path),
        "control_id": payload["id"],
        "action": payload["action"],
    }, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    runtime_dir = runtime_dir_arg(args.runtime_dir)
    checkpoint = runtime_dir / "checkpoint.json"
    if not checkpoint.exists():
        print(json.dumps({
            "ok": False,
            "runtime_dir": str(runtime_dir),
            "error": "checkpoint.json not found",
        }, indent=2))
        return 1
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    print(json.dumps({
        "ok": True,
        "runtime_dir": str(runtime_dir),
        "checkpoint_path": str(checkpoint),
        "runtime_state": data.get("runtime_state"),
        "campaign_id": data.get("campaign_id"),
        "phase": data.get("phase"),
        "control": {
            "path": data.get("control_path"),
            "last_id": data.get("last_control_id"),
            "last_action": data.get("last_control_action"),
            "last_status": data.get("last_control_status"),
        },
        "position": {
            "id": data.get("position_id"),
            "direction": data.get("position_direction"),
            "quantity": data.get("position_quantity"),
            "average_price": data.get("position_average_price"),
        },
        "updated_utc": data.get("updated_utc"),
    }, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Write KahnRuntime control commands.")
    p.add_argument(
        "--runtime-dir",
        default=str(DEFAULT_RUNTIME_DIR),
        help="Kahn runtime directory containing control.json/checkpoint.json.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    for name, action, help_text in (
        ("flat", "FLAT", "Cancel Kahn-owned working orders, close bound position(s), and retire the campaign."),
        ("flatten", "FLAT", "Alias for flat."),
        ("cancel", "CANCEL", "Cancel/retire the campaign only when the bound position is flat."),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.set_defaults(func=command_control, action=action)
        cmd.add_argument("--reason", default=None)

    status = sub.add_parser("status", help="Read Kahn checkpoint summary.")
    status.set_defaults(func=command_status)
    return p


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
