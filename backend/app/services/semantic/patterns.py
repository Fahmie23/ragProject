from __future__ import annotations

import re


# Keep lexical callout recovery deliberately narrow.  Phrases such as
# ``Guidance on ...`` and ``Examples of ...`` are common *document/appendix
# titles* or ordinary prose, so matching them here can flatten real outline
# structure.  Ambiguous labels can still be resolved from layout/heading
# context by the dedicated scope resolvers.
_CALLOUT_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"guidance(?:\s+for\b|\s*:)|"
    r"note\s*:|"
    r"notes?\s+for\b|"
    r"example\s*:|"
    r"warning\s*:|"
    r"caution\s*:|"
    r"explanatory\s+note\b|"
    # Source/reference labels beneath figures or illustrations are local
    # supplementary scope, not persistent outline headings.  Deliberately do
    # not match topic headings such as ``Source of Information ...``.
    r"source\s+for\b.*:?\s*$|"
    r"for\s+full\b.*\bsource\s+for\b.*:?\s*$"
    r")",
    re.IGNORECASE,
)

_TERMINAL_SENTENCE_RE = re.compile(r"[.!?]\s*$")


def normalize_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def is_callout_heading(text: str) -> bool:
    """Return True for explicit local advisory/supplementary callout labels.

    The matcher intentionally favors precision over recall.  Broad title-like
    phrases (for example ``Guidance on ...``) are not lexical callouts because
    they also occur as genuine appendix/document titles.  Other semantic passes
    may still demote such elements when layout and neighboring structure provide
    stronger local-scope evidence.
    """
    return _CALLOUT_HEADING_RE.match(normalize_text(text)) is not None


def ends_complete_sentence(text: str) -> bool:
    return _TERMINAL_SENTENCE_RE.search(normalize_text(text)) is not None
