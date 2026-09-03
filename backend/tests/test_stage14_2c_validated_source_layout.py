from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SHELL = REPO_ROOT / "frontend" / "src" / "app" / "RagWorkbenchShell.tsx"
STYLES = REPO_ROOT / "frontend" / "src" / "styles.css"


def test_validated_source_uses_bounded_preview_and_explicit_full_evidence_disclosure() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'className="rag-source-preview"' in text
    assert 'className="rag-source-evidence-disclosure"' in text
    assert '<summary>Show full evidence</summary>' in text
    assert 'className="rag-source-evidence-full"' in text
    assert 'className="rag-source-meta"' in text
    assert 'className="rag-citation-open"' in text


def test_validated_source_preview_clips_instead_of_overflowing() -> None:
    css = STYLES.read_text(encoding="utf-8")
    assert '.rag-source-preview {' in css
    preview = css.split('.rag-source-preview {', 1)[1].split('}', 1)[0]
    assert 'overflow: hidden;' in preview
    assert '-webkit-line-clamp: 6;' in preview
    assert 'overflow-wrap: anywhere;' in preview
    assert 'overflow: visible;' not in preview


def test_full_evidence_scrolls_only_after_user_expands_it() -> None:
    css = STYLES.read_text(encoding="utf-8")
    full = css.split('.rag-source-evidence-full {', 1)[1].split('}', 1)[0]
    assert 'max-height: 260px;' in full
    assert 'overflow: auto;' in full
    assert 'overscroll-behavior: contain;' in full


def test_source_card_and_footer_metadata_cannot_escape_narrow_sidebar() -> None:
    css = STYLES.read_text(encoding="utf-8")
    card = css.split('.rag-citation-source-card {', 1)[1].split('}', 1)[0]
    meta = css.split('.rag-source-meta {', 1)[1].split('}', 1)[0]
    assert 'overflow: hidden;' in card
    assert 'overflow-wrap: anywhere;' in meta
