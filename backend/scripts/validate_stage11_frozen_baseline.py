#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.baseline_guard import load_manifest, validate_frozen_baseline  # noqa: E402

DEFAULT_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_frozen_pipeline_manifest_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the frozen Stage 11 production baseline hashes")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    result = validate_frozen_baseline(backend_root=BACKEND_ROOT, manifest=manifest)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Baseline: {result['baseline_id']}")
        print(f"Checked: {result['checked_file_count']} files")
        print(f"Status: {'PASS' if result['valid'] else 'FAIL'}")
        for error in result["errors"]:
            print(f"- {error}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
