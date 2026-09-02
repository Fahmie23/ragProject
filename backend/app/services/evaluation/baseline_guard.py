"""Hash-based guard for frozen Stage 11 production inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("baseline manifest must be a JSON object")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("baseline manifest.files must be a non-empty object")
    return data


def validate_frozen_baseline(*, backend_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    checked: list[dict[str, Any]] = []
    errors: list[str] = []
    for relative_path, expected_sha in manifest["files"].items():
        path = backend_root.parent / relative_path if str(relative_path).startswith("backend/") else backend_root / relative_path
        if not path.exists():
            errors.append(f"missing frozen file: {relative_path}")
            checked.append({"path": relative_path, "ok": False, "expected_sha256": expected_sha, "actual_sha256": None})
            continue
        actual_sha = sha256_file(path)
        ok = actual_sha == expected_sha
        checked.append({
            "path": relative_path,
            "ok": ok,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
        })
        if not ok:
            errors.append(f"frozen file hash mismatch: {relative_path}")
    return {
        "baseline_id": manifest.get("baseline_id"),
        "valid": not errors,
        "checked_file_count": len(checked),
        "errors": errors,
        "files": checked,
    }
