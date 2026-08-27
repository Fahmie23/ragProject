from __future__ import annotations

import argparse
import sys

from app.services.evaluation.stage4_golden import (
    load_golden_spec,
    validate_golden_spec,
    validate_golden_spec_against_pdf,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage 4 golden specification integrity and source anchors.")
    parser.add_argument("--spec", required=True, help="Path to golden specification JSON")
    parser.add_argument("--pdf", help="Optional benchmark PDF path; validates SHA/page count/text anchors")
    args = parser.parse_args()

    spec = load_golden_spec(args.spec)
    issues = validate_golden_spec_against_pdf(args.pdf, spec) if args.pdf else validate_golden_spec(spec)
    if issues:
        print(f"Golden specification INVALID ({len(issues)} issue(s))")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Golden specification valid.")
    if args.pdf:
        print("Source SHA, page count, and every element text anchor were verified against the PDF.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
