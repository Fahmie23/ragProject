from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.config import settings
from app.routers.documents import get_visual_preview
from app.schemas import ChunkingArtifact, ResolvedStructureArtifact
from app.services.visuals import build_visual_reference_map, enrich_rows_with_visual_refs, visual_crop


DOCUMENT_ID = "485c4989-c300-45c8-ac06-79a59492bb5c"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(autouse=True)
def _use_real_visual_fixture_data(monkeypatch: pytest.MonkeyPatch):
    """Point storage-backed Option-A checks at the read-only real-document fixture.

    The Docker ``backend-test`` service intentionally uses ``DATA_DIR=/tmp/rag-data``
    so ordinary tests cannot mutate the checked-in corpus. These visual-evidence
    integration checks are read-only and deliberately exercise the frozen SC PDF
    artifacts, so scope the shared settings object to ``backend/data`` only for this
    module. ``monkeypatch`` restores the original test setting after each test.
    """

    monkeypatch.setattr(settings, "data_dir", DATA_DIR)
    yield


def _artifacts() -> tuple[ResolvedStructureArtifact, ChunkingArtifact]:
    resolved = ResolvedStructureArtifact.model_validate_json(
        (DATA_DIR / "resolved" / f"{DOCUMENT_ID}.json").read_text(encoding="utf-8")
    )
    chunks = ChunkingArtifact.model_validate_json(
        (DATA_DIR / "chunks" / f"{DOCUMENT_ID}.json").read_text(encoding="utf-8")
    )
    return resolved, chunks


def _chunk_by_index(artifact: ChunkingArtifact, index: int):
    return next(chunk for chunk in artifact.chunks if chunk.chunk_index == index)


def _visual_ids(refs):
    return {(ref.asset_type, ref.visual_id, ref.page_number) for ref in refs}


def test_visual_relationship_resolver_matches_real_sc_figures() -> None:
    resolved, artifact = _artifacts()
    ref_map = build_visual_reference_map(resolved.structure, artifact.chunks)

    # The RBA explanation finishes on PDF page 69 and explicitly introduces a
    # diagram on page 70. The resolver should bridge that one-page boundary.
    rba_a = _chunk_by_index(artifact, 181)
    rba_b = _chunk_by_index(artifact, 182)
    assert ("figure", "figure-5", 70) in _visual_ids(ref_map[rba_a.chunk_id])
    assert ("figure", "figure-5", 70) in _visual_ids(ref_map[rba_b.chunk_id])

    # The clauses after the diagram must not inherit it merely because they are
    # physically nearby on page 70.
    after_rba = _chunk_by_index(artifact, 183)
    assert ("figure", "figure-5", 70) not in _visual_ids(ref_map[after_rba.chunk_id])

    # Appendix E's four beneficial-ownership examples have direct canonical
    # explanation relationships to their corresponding illustrations.
    for chunk_index, figure_id, page_number in [
        (267, "figure-6", 99),
        (268, "figure-7", 100),
        (269, "figure-8", 101),
        (270, "figure-9", 102),
    ]:
        chunk = _chunk_by_index(artifact, chunk_index)
        refs = ref_map[chunk.chunk_id]
        assert ("figure", figure_id, page_number) in _visual_ids(refs)
        assert max(ref.confidence for ref in refs if ref.visual_id == figure_id) >= 0.97

    # Appendix F explicitly says that an overview is set out in Illustration 1
    # below. Both nearest preceding chunks are eligible, without changing rank.
    for chunk_index in (272, 273):
        chunk = _chunk_by_index(artifact, chunk_index)
        assert ("figure", "figure-10", 104) in _visual_ids(ref_map[chunk.chunk_id])


def test_visual_relationship_resolver_ignores_cover_art_false_positives() -> None:
    resolved, artifact = _artifacts()
    ref_map = build_visual_reference_map(resolved.structure, artifact.chunks)
    emitted = {ref.visual_id for refs in ref_map.values() for ref in refs}
    assert emitted.isdisjoint({"figure-1", "figure-2", "figure-3", "figure-4"})


def test_table_visual_reference_requires_actual_table_provenance() -> None:
    resolved, artifact = _artifacts()
    ref_map = build_visual_reference_map(resolved.structure, artifact.chunks)
    table_chunk = next(chunk for chunk in artifact.chunks if "p74-e2" in chunk.source_element_ids)
    refs = ref_map[table_chunk.chunk_id]
    table_refs = [ref for ref in refs if ref.asset_type == "table"]
    assert table_refs
    assert table_refs[0].visual_id == "table-8"
    assert table_refs[0].page_number == 74
    assert table_refs[0].relation == "table_content"
    assert table_refs[0].confidence == 1.0


def test_visual_crop_geometry_renders_real_pdf_pixels() -> None:
    resolved, _ = _artifacts()
    structure = resolved.structure
    figure_page, figure_bbox = visual_crop(
        structure,
        asset_type="figure",
        visual_id="figure-6",
    )
    table_page, table_bbox = visual_crop(
        structure,
        asset_type="table",
        visual_id="table-8",
        page_number=74,
    )
    assert figure_page == 99
    assert table_page == 74
    assert figure_bbox[2] > figure_bbox[0] and figure_bbox[3] > figure_bbox[1]
    assert table_bbox[2] > table_bbox[0] and table_bbox[3] > table_bbox[1]

    pdf_path = DATA_DIR / "raw" / f"{DOCUMENT_ID}.pdf"
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[figure_page - 1]
        clip = pymupdf.Rect(*figure_bbox) & page.rect
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2), clip=clip, alpha=False)
        png = pixmap.tobytes("png")
        assert png.startswith(b"\x89PNG")
        assert len(png) > 10_000
    finally:
        doc.close()


def test_request_time_enrichment_serializes_visual_refs_without_changing_row_data() -> None:
    _, artifact = _artifacts()
    figure_chunk = _chunk_by_index(artifact, 267)
    raw_row = {
        "chunk_id": figure_chunk.chunk_id,
        "rank": 1,
        "content_text": figure_chunk.content_text,
    }
    enriched = enrich_rows_with_visual_refs(DOCUMENT_ID, [raw_row])
    assert len(enriched) == 1
    assert enriched[0]["rank"] == 1
    assert enriched[0]["content_text"] == figure_chunk.content_text
    assert enriched[0]["visual_refs"][0]["visual_id"] == "figure-6"
    assert enriched[0]["visual_refs"][0]["page_number"] == 99


def test_visual_preview_endpoint_function_renders_crop_and_highlighted_page() -> None:
    crop = get_visual_preview(
        DOCUMENT_ID,
        "figure",
        "figure-6",
        page_number=99,
        scale=1.0,
        padding=8.0,
        view="crop",
    )
    page = get_visual_preview(
        DOCUMENT_ID,
        "table",
        "table-8",
        page_number=74,
        scale=1.0,
        padding=8.0,
        view="page",
    )
    assert crop.media_type == "image/png"
    assert page.media_type == "image/png"
    assert crop.body.startswith(b"\x89PNG") and len(crop.body) > 10_000
    assert page.body.startswith(b"\x89PNG") and len(page.body) > 10_000
    assert crop.headers["cache-control"] == "private, max-age=300"
