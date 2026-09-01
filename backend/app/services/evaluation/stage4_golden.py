from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from app.schemas import CanonicalElement, StructuredDocument


def normalize_text(value: str) -> str:
    """Normalize PDF/canonical text for stable golden matching.

    Golden anchors intentionally match semantic text rather than element ids or
    exact line wrapping.  This keeps the benchmark stable when reading-order or
    span reconstruction improves without changing the document meaning.
    """
    normalized = " ".join((value or "").replace("\u00ad", "").split()).strip()
    # PDF text extraction often drops the visual gap after enumeration or
    # footnote markers (``(a)Full`` / ``1Regulation``).  Golden anchors care
    # about semantic text, not that harmless glyph-spacing artifact.
    normalized = re.sub(
        r"^(\((?:[A-Za-z]|\d{1,2}|[ivxlcdmIVXLCDM]{1,6})\))\s*",
        lambda match: f"{match.group(1)} ",
        normalized,
        count=1,
    )
    normalized = re.sub(r"^(\d{1,2})(?=[A-Za-z])", r"\1 ", normalized, count=1)
    return normalized.strip()


@dataclass
class GoldenCheck:
    check_id: str
    category: str
    strength: str
    passed: bool
    message: str
    matched_element_ids: list[str] = field(default_factory=list)


@dataclass
class GoldenEvaluationReport:
    benchmark_id: str
    spec_version: str
    source_match: bool
    required_passed: int
    required_total: int
    advisory_passed: int
    advisory_total: int
    checks: list[GoldenCheck] = field(default_factory=list)
    open_questions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def required_score(self) -> float:
        if self.required_total == 0:
            return 1.0
        return self.required_passed / self.required_total

    @property
    def advisory_score(self) -> float:
        if self.advisory_total == 0:
            return 1.0
        return self.advisory_passed / self.advisory_total

    @property
    def passed(self) -> bool:
        return self.source_match and self.required_passed == self.required_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "spec_version": self.spec_version,
            "source_match": self.source_match,
            "passed": self.passed,
            "required": {
                "passed": self.required_passed,
                "total": self.required_total,
                "score": self.required_score,
            },
            "advisory": {
                "passed": self.advisory_passed,
                "total": self.advisory_total,
                "score": self.advisory_score,
            },
            "checks": [check.__dict__ for check in self.checks],
            "open_questions": self.open_questions,
        }


def load_golden_spec(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _all_elements(structure: StructuredDocument) -> list[CanonicalElement]:
    return [element for page in structure.pages for element in page.elements]


def _match_text(text: str, match: dict[str, Any]) -> bool:
    candidate = normalize_text(text)
    candidate_cmp = candidate if match.get("case_sensitive") else candidate.casefold()

    def norm(value: str) -> str:
        value = normalize_text(value)
        return value if match.get("case_sensitive") else value.casefold()

    if "exact" in match and candidate_cmp != norm(match["exact"]):
        return False
    if "starts_with" in match and not candidate_cmp.startswith(norm(match["starts_with"])):
        return False
    if "contains" in match and norm(match["contains"]) not in candidate_cmp:
        return False
    if "regex" in match:
        flags = 0 if match.get("case_sensitive") else re.IGNORECASE
        if re.search(match["regex"], candidate, flags=flags) is None:
            return False
    return True


def _matching_elements(
    elements: list[CanonicalElement],
    assertion: dict[str, Any],
) -> list[CanonicalElement]:
    match = assertion.get("match", {})
    page = assertion.get("page")
    matches: list[CanonicalElement] = []
    for element in elements:
        if page is not None and element.page_number != page:
            continue
        if not _match_text(element.text, match):
            continue
        matches.append(element)
    return matches


def _check_expectations(element: CanonicalElement, expect: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if "type" in expect and element.type != expect["type"]:
        failures.append(f"type={element.type!r}, expected {expect['type']!r}")
    if "not_type" in expect and element.type == expect["not_type"]:
        failures.append(f"type must not be {expect['not_type']!r}")
    if "clause_number" in expect and element.clause_number != expect["clause_number"]:
        failures.append(f"clause_number={element.clause_number!r}, expected {expect['clause_number']!r}")
    if "layout_role" in expect and element.layout_role != expect["layout_role"]:
        failures.append(f"layout_role={element.layout_role!r}, expected {expect['layout_role']!r}")
    if "heading_level" in expect and element.heading_level != expect["heading_level"]:
        failures.append(f"heading_level={element.heading_level!r}, expected {expect['heading_level']!r}")
    if "heading_level_source" in expect and element.heading_level_source != expect["heading_level_source"]:
        failures.append(
            f"heading_level_source={element.heading_level_source!r}, expected {expect['heading_level_source']!r}"
        )
    if "min_confidence" in expect:
        confidence = element.classification.confidence if element.classification else None
        if confidence is None or confidence < float(expect["min_confidence"]):
            failures.append(f"confidence={confidence!r}, expected >= {float(expect['min_confidence']):.2f}")
    if "section_record" in expect:
        # Evaluated later where section records are available.
        pass
    return failures


def _add_check(
    checks: list[GoldenCheck],
    *,
    check_id: str,
    category: str,
    strength: str,
    passed: bool,
    message: str,
    matched_element_ids: list[str] | None = None,
) -> None:
    checks.append(
        GoldenCheck(
            check_id=check_id,
            category=category,
            strength=strength,
            passed=passed,
            message=message,
            matched_element_ids=matched_element_ids or [],
        )
    )


def evaluate_stage4_golden(
    structure: StructuredDocument,
    spec: dict[str, Any],
) -> GoldenEvaluationReport:
    elements = _all_elements(structure)
    element_by_id = {element.element_id: element for element in elements}
    sections_by_element = {section.element_id: section for section in structure.sections}
    source = spec.get("source", {})
    source_match = True
    if source.get("sha256") and structure.source_sha256 != source["sha256"]:
        source_match = False
    if source.get("page_count") and structure.summary.page_count != source["page_count"]:
        source_match = False

    checks: list[GoldenCheck] = []
    anchors: dict[str, CanonicalElement] = {}

    for assertion in spec.get("element_assertions", []):
        check_id = assertion["id"]
        strength = assertion.get("strength", "required")
        matches = _matching_elements(elements, assertion)
        expected_count = int(assertion.get("expect_count", 1))
        if len(matches) != expected_count:
            _add_check(
                checks,
                check_id=check_id,
                category="element",
                strength=strength,
                passed=False,
                message=f"expected {expected_count} element match(es), found {len(matches)}",
                matched_element_ids=[element.element_id for element in matches],
            )
            continue
        if expected_count == 0:
            _add_check(
                checks,
                check_id=check_id,
                category="element",
                strength=strength,
                passed=True,
                message="ok",
            )
            continue
        if expected_count != 1:
            _add_check(
                checks,
                check_id=check_id,
                category="element",
                strength=strength,
                passed=False,
                message="element expectation checks currently require expect_count 0 or 1",
                matched_element_ids=[element.element_id for element in matches],
            )
            continue
        element = matches[0]
        anchors[check_id] = element
        failures = _check_expectations(element, assertion.get("expect", {}))
        section_expectation = assertion.get("expect", {}).get("section_record")
        if section_expectation is True and element.element_id not in sections_by_element:
            failures.append("expected a SectionRecord for this element")
        elif section_expectation is False and element.element_id in sections_by_element:
            failures.append("element must not create a SectionRecord")
        _add_check(
            checks,
            check_id=check_id,
            category="element",
            strength=strength,
            passed=not failures,
            message="ok" if not failures else "; ".join(failures),
            matched_element_ids=[element.element_id],
        )

    for assertion in spec.get("relation_assertions", []):
        check_id = assertion["id"]
        strength = assertion.get("strength", "required")
        source_anchor = anchors.get(assertion["source"])
        target_anchor = anchors.get(assertion["target"])
        if source_anchor is None or target_anchor is None:
            _add_check(
                checks,
                check_id=check_id,
                category="relation",
                strength=strength,
                passed=False,
                message="source or target anchor did not resolve",
            )
            continue
        relation_type = assertion["type"]
        found = any(
            relation.type == relation_type
            and relation.source_element_id == source_anchor.element_id
            and relation.target_element_id == target_anchor.element_id
            for relation in structure.relationships
        )
        expected_present = assertion.get("present", True)
        passed = found == expected_present
        _add_check(
            checks,
            check_id=check_id,
            category="relation",
            strength=strength,
            passed=passed,
            message=(
                "ok"
                if passed
                else f"relation {relation_type} present={found}, expected present={expected_present}"
            ),
            matched_element_ids=[source_anchor.element_id, target_anchor.element_id],
        )

    definitions_by_term = {normalize_text(item.term).casefold(): item for item in structure.definitions}
    for assertion in spec.get("definition_assertions", []):
        check_id = assertion["id"]
        strength = assertion.get("strength", "required")
        term = normalize_text(assertion["term"]).casefold()
        definition = definitions_by_term.get(term)
        failures: list[str] = []
        if definition is None:
            failures.append("definition term not found")
        else:
            expect = assertion.get("expect", {})
            if "start_page" in expect and definition.start_page != expect["start_page"]:
                failures.append(f"start_page={definition.start_page}, expected {expect['start_page']}")
            if "end_page" in expect and definition.end_page != expect["end_page"]:
                failures.append(f"end_page={definition.end_page}, expected {expect['end_page']}")
            if "spans_multiple_pages" in expect and definition.spans_multiple_pages != expect["spans_multiple_pages"]:
                failures.append(
                    f"spans_multiple_pages={definition.spans_multiple_pages}, expected {expect['spans_multiple_pages']}"
                )
            if "min_item_count" in expect and len(definition.items) < int(expect["min_item_count"]):
                failures.append(f"item_count={len(definition.items)}, expected >= {expect['min_item_count']}")
            if "definition_contains" in expect:
                haystack = normalize_text(definition.definition_text).casefold()
                needle = normalize_text(expect["definition_contains"]).casefold()
                if needle not in haystack:
                    failures.append(f"definition text does not contain {expect['definition_contains']!r}")
        _add_check(
            checks,
            check_id=check_id,
            category="definition",
            strength=strength,
            passed=not failures,
            message="ok" if not failures else "; ".join(failures),
        )

    for assertion in spec.get("appendix_assertions", []):
        check_id = assertion["id"]
        strength = assertion.get("strength", "required")
        label = normalize_text(assertion["label"]).casefold()
        candidates = [item for item in structure.appendices if normalize_text(item.label).casefold() == label]
        failures: list[str] = []
        if len(candidates) != 1:
            failures.append(f"expected one appendix record, found {len(candidates)}")
        else:
            appendix = candidates[0]
            expect = assertion.get("expect", {})
            if "start_page" in expect and appendix.start_page != expect["start_page"]:
                failures.append(f"start_page={appendix.start_page}, expected {expect['start_page']}")
            if "end_page" in expect and appendix.end_page != expect["end_page"]:
                failures.append(f"end_page={appendix.end_page}, expected {expect['end_page']}")
            if "title_contains" in expect:
                title = normalize_text(appendix.title or "").casefold()
                if normalize_text(expect["title_contains"]).casefold() not in title:
                    failures.append(f"appendix title does not contain {expect['title_contains']!r}")
        _add_check(
            checks,
            check_id=check_id,
            category="appendix",
            strength=strength,
            passed=not failures,
            message="ok" if not failures else "; ".join(failures),
        )

    for assertion in spec.get("logical_table_assertions", []):
        check_id = assertion["id"]
        strength = assertion.get("strength", "required")
        candidates = structure.tables
        if "start_page" in assertion:
            candidates = [item for item in candidates if item.start_page == assertion["start_page"]]
        if "end_page" in assertion:
            candidates = [item for item in candidates if item.end_page == assertion["end_page"]]
        if "min_col_count" in assertion:
            candidates = [item for item in candidates if item.col_count >= assertion["min_col_count"]]
        if "min_row_count" in assertion:
            candidates = [item for item in candidates if item.row_count >= assertion["min_row_count"]]
        passed = bool(candidates)
        _add_check(
            checks,
            check_id=check_id,
            category="logical_table",
            strength=strength,
            passed=passed,
            message="ok" if passed else "no logical table matched the expected page/shape constraints",
        )

    for assertion in spec.get("page_assertions", []):
        check_id = assertion["id"]
        strength = assertion.get("strength", "required")
        page_number = assertion["page"]
        page = next((page for page in structure.pages if page.page_number == page_number), None)
        failures: list[str] = []
        if page is None:
            failures.append("page missing from StructuredDocument")
        else:
            counts: dict[str, int] = {}
            for element in page.elements:
                counts[element.type] = counts.get(element.type, 0) + 1
            for semantic_type, minimum in assertion.get("min_type_counts", {}).items():
                actual = counts.get(semantic_type, 0)
                if actual < int(minimum):
                    failures.append(f"{semantic_type} count={actual}, expected >= {minimum}")
        _add_check(
            checks,
            check_id=check_id,
            category="page",
            strength=strength,
            passed=not failures,
            message="ok" if not failures else "; ".join(failures),
        )

    for assertion in spec.get("figure_assertions", []):
        check_id = assertion["id"]
        strength = assertion.get("strength", "required")
        page_number = assertion["page"]
        figures = [item for item in structure.figures if item.page_number == page_number]
        minimum = int(assertion.get("min_count", 1))
        passed = len(figures) >= minimum
        _add_check(
            checks,
            check_id=check_id,
            category="figure",
            strength=strength,
            passed=passed,
            message="ok" if passed else f"figure_count={len(figures)}, expected >= {minimum}",
        )

    required = [check for check in checks if check.strength == "required"]
    advisory = [check for check in checks if check.strength == "advisory"]
    return GoldenEvaluationReport(
        benchmark_id=spec.get("benchmark_id", "stage4-golden"),
        spec_version=spec.get("spec_version", "unknown"),
        source_match=source_match,
        required_passed=sum(check.passed for check in required),
        required_total=len(required),
        advisory_passed=sum(check.passed for check in advisory),
        advisory_total=len(advisory),
        checks=checks,
        open_questions=list(spec.get("open_questions", [])),
    )


def evaluate_stage4_golden_files(
    structure_path: str | Path,
    spec_path: str | Path,
) -> GoldenEvaluationReport:
    structure = StructuredDocument.model_validate_json(Path(structure_path).read_text(encoding="utf-8"))
    spec = load_golden_spec(spec_path)
    return evaluate_stage4_golden(structure, spec)


def validate_golden_spec(spec: dict[str, Any]) -> list[str]:
    """Validate internal golden-spec references before any Stage 4 run is scored."""
    issues: list[str] = []
    seen_ids: set[str] = set()
    anchor_ids: set[str] = set()

    categories = (
        "element_assertions",
        "relation_assertions",
        "definition_assertions",
        "appendix_assertions",
        "logical_table_assertions",
        "page_assertions",
        "figure_assertions",
    )
    for category in categories:
        for assertion in spec.get(category, []):
            check_id = assertion.get("id")
            if not check_id:
                issues.append(f"{category} contains an assertion without id")
                continue
            if check_id in seen_ids:
                issues.append(f"duplicate check id: {check_id}")
            seen_ids.add(check_id)
            if category == "element_assertions":
                anchor_ids.add(check_id)
                match = assertion.get("match", {})
                supported = {"exact", "starts_with", "contains", "regex"}
                if not any(key in match for key in supported):
                    issues.append(f"element assertion {check_id} has no supported text matcher")

    for relation in spec.get("relation_assertions", []):
        if relation.get("source") not in anchor_ids:
            issues.append(f"relation {relation.get('id')} references unknown source anchor {relation.get('source')!r}")
        if relation.get("target") not in anchor_ids:
            issues.append(f"relation {relation.get('id')} references unknown target anchor {relation.get('target')!r}")

    page_count = spec.get("source", {}).get("page_count")
    if page_count:
        for assertion in spec.get("element_assertions", []) + spec.get("page_assertions", []) + spec.get("figure_assertions", []):
            page = assertion.get("page")
            if page is not None and not (1 <= int(page) <= int(page_count)):
                issues.append(f"assertion {assertion.get('id')} references invalid page {page}")
        for item in spec.get("coverage_matrix", []):
            for page in item.get("pages", []):
                if not (1 <= int(page) <= int(page_count)):
                    issues.append(f"coverage matrix references invalid page {page}")
    return issues


def validate_golden_spec_against_pdf(
    pdf_path: str | Path,
    spec: dict[str, Any],
) -> list[str]:
    """Check that golden anchors really exist in the benchmark PDF.

    This is a source-grounding check only; it does not infer Stage 4 semantics.
    It catches typos, wrong page numbers and stale source hashes in the golden
    file before those mistakes are mistaken for parser regressions.
    """
    issues = validate_golden_spec(spec)
    if issues:
        return issues

    import hashlib
    import pymupdf

    path = Path(pdf_path)
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    expected_sha = spec.get("source", {}).get("sha256")
    if expected_sha and actual_sha != expected_sha:
        issues.append(f"source sha256 mismatch: {actual_sha} != {expected_sha}")

    doc = pymupdf.open(path)
    expected_pages = spec.get("source", {}).get("page_count")
    if expected_pages and doc.page_count != int(expected_pages):
        issues.append(f"source page_count mismatch: {doc.page_count} != {expected_pages}")

    page_text: dict[int, str] = {
        page_number: normalize_text(doc[page_number - 1].get_text("text"))
        for page_number in {
            int(item["page"])
            for item in spec.get("element_assertions", [])
            if item.get("page") is not None
        }
    }

    for assertion in spec.get("element_assertions", []):
        page = int(assertion["page"])
        text = page_text.get(page, "")
        match = assertion.get("match", {})
        found = False
        if "exact" in match:
            found = normalize_text(match["exact"]).casefold() in text.casefold()
        elif "starts_with" in match:
            found = normalize_text(match["starts_with"]).casefold() in text.casefold()
        elif "contains" in match:
            found = normalize_text(match["contains"]).casefold() in text.casefold()
        elif "regex" in match:
            flags = 0 if match.get("case_sensitive") else re.IGNORECASE
            found = re.search(match["regex"], text, flags=flags) is not None
        if not found:
            issues.append(f"source anchor {assertion['id']} not found on PDF page {page}")

    full_text = normalize_text(" ".join(doc[index].get_text("text") for index in range(doc.page_count))).casefold()
    for assertion in spec.get("definition_assertions", []):
        if normalize_text(assertion["term"]).casefold() not in full_text:
            issues.append(f"definition term {assertion['term']!r} is not present in the benchmark PDF")
    for assertion in spec.get("appendix_assertions", []):
        if normalize_text(assertion["label"]).casefold() not in full_text:
            issues.append(f"appendix label {assertion['label']!r} is not present in the benchmark PDF")

    doc.close()
    return issues
