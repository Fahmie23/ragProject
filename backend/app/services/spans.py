from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.schemas import PageExtraction, TextBlock, TextLine, TextSpan


@dataclass(frozen=True)
class SpanEvidence:
    page_number: int
    block_id: str
    line_id: str
    span_id: str
    block_index: int
    line_index: int
    span_index: int
    text: str
    bbox: list[float]
    font: str | None
    size: float | None


def stable_line_id(page_number: int, block: TextBlock, line_index: int, line: TextLine | None = None) -> str:
    if line is not None and line.line_id:
        return line.line_id
    return f"{block.block_id}-l{line_index + 1}"


def stable_span_id(
    page_number: int,
    block: TextBlock,
    line_index: int,
    span_index: int,
    *,
    line: TextLine | None = None,
    span: TextSpan | None = None,
) -> str:
    if span is not None and span.span_id:
        return span.span_id
    line_id = stable_line_id(page_number, block, line_index, line)
    return f"{line_id}-s{span_index + 1}"


def iter_page_spans(page: PageExtraction) -> Iterable[SpanEvidence]:
    """Yield text spans with deterministic IDs, including legacy Stage-3 JSON.

    Stage 3 schema 1.1 persists ``line_id`` and ``span_id``. Older 1.0
    extraction artifacts do not have them, so this iterator deterministically
    synthesizes the same IDs from block/line/span nesting. This keeps span
    corrections backward-compatible without rewriting immutable extraction
    artifacts.
    """
    for block_index, block in enumerate(page.blocks):
        if getattr(block, "type", None) != "text":
            continue
        assert isinstance(block, TextBlock)
        for line_index, line in enumerate(block.lines):
            line_id = stable_line_id(page.page_number, block, line_index, line)
            for span_index, span in enumerate(line.spans):
                span_id = stable_span_id(
                    page.page_number,
                    block,
                    line_index,
                    span_index,
                    line=line,
                    span=span,
                )
                yield SpanEvidence(
                    page_number=page.page_number,
                    block_id=block.block_id,
                    line_id=line_id,
                    span_id=span_id,
                    block_index=block_index,
                    line_index=line_index,
                    span_index=span_index,
                    text=span.text,
                    bbox=list(span.bbox),
                    font=span.font,
                    size=span.size,
                )


def span_map(page: PageExtraction) -> dict[str, SpanEvidence]:
    return {item.span_id: item for item in iter_page_spans(page)}


def line_map(page: PageExtraction) -> dict[str, list[SpanEvidence]]:
    result: dict[str, list[SpanEvidence]] = {}
    for item in iter_page_spans(page):
        result.setdefault(item.line_id, []).append(item)
    return result
