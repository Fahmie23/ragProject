from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Small deterministic query-only stopword set. PostgreSQL still performs its own
# English stemming/stopword normalization after this step. The purpose here is
# to remove question scaffolding so lexical candidate generation is not forced
# to match natural-language filler words.
_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "how", "i", "if", "in", "into", "is", "it", "its", "may", "must", "not", "of", "on", "or",
    "shall", "should", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "to", "was", "we", "were", "what", "when", "where", "which",
    "who", "why", "will", "with", "would", "you", "your",
}


@dataclass(frozen=True)
class LexicalQueryPlan:
    original_query: str
    terms: tuple[str, ...]
    tsquery_text: str
    mode: str = "or_content_terms_v1"


def build_lexical_query_plan(query: str, *, max_terms: int = 24) -> LexicalQueryPlan:
    """Build an OR-oriented PostgreSQL tsquery from meaningful query terms.

    Stage 7 used ``websearch_to_tsquery`` over the complete natural-language
    question. That can be too strict for paraphrases because several question
    words/phrases must match together. Stage 7.1 instead removes deterministic
    question scaffolding and joins the remaining terms with OR. PostgreSQL then
    applies the ``english`` configuration for stemming and stopword handling.

    The transformation is intentionally deterministic and model-free so it can
    be inspected in retrieval traces and reproduced in evaluation.
    """

    clean_query = query.strip()
    if not clean_query:
        raise ValueError("Lexical query cannot be empty.")
    if max_terms < 1:
        raise ValueError("max_terms must be at least 1.")

    raw_tokens = [match.group(0).lower() for match in _TOKEN_RE.finditer(clean_query)]
    if not raw_tokens:
        raise ValueError("Lexical query does not contain searchable terms.")

    terms: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        if token in _QUERY_STOPWORDS:
            continue
        # Single-character alphabetic tokens are almost always noise; retain
        # digits because clause numbers/year fragments can still be meaningful.
        if len(token) == 1 and token.isalpha():
            continue
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= max_terms:
            break

    # Do not turn a short query composed entirely of stopwords into an empty
    # retrieval request. Fall back to unique raw tokens and let PostgreSQL's
    # English configuration decide whether any survive its own normalization.
    if not terms:
        for token in raw_tokens:
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
            if len(terms) >= max_terms:
                break

    tsquery_text = " | ".join(terms)
    return LexicalQueryPlan(
        original_query=clean_query,
        terms=tuple(terms),
        tsquery_text=tsquery_text,
    )
