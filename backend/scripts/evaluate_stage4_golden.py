from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.services.evaluation.stage4_golden import evaluate_stage4_golden_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a Stage 4 StructuredDocument against a golden specification.")
    parser.add_argument("--structure", required=True, help="Path to Stage 4 StructuredDocument JSON")
    parser.add_argument("--spec", required=True, help="Path to golden specification JSON")
    parser.add_argument("--json", action="store_true", help="Print the full machine-readable report")
    args = parser.parse_args()

    report = evaluate_stage4_golden_files(Path(args.structure), Path(args.spec))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Benchmark: {report.benchmark_id} ({report.spec_version})")
        print(f"Source match: {'yes' if report.source_match else 'NO'}")
        print(
            f"Required: {report.required_passed}/{report.required_total} "
            f"({report.required_score * 100:.1f}%)"
        )
        if report.advisory_total:
            print(
                f"Advisory: {report.advisory_passed}/{report.advisory_total} "
                f"({report.advisory_score * 100:.1f}%)"
            )
        failed = [check for check in report.checks if not check.passed]
        if failed:
            print("\nFailed checks:")
            for check in failed:
                print(f"- [{check.strength}] {check.check_id}: {check.message}")
        if report.open_questions:
            print(f"\nOpen taxonomy questions: {len(report.open_questions)}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
