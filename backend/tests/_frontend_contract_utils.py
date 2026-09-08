from __future__ import annotations

import re
from pathlib import Path


def read_css_bundle(entrypoint: Path) -> str:
    """Read the CSS entrypoint plus its local @import modules in cascade order.

    The frontend intentionally keeps styles.css as a small import manifest after the
    UI revamp, so contract tests must inspect the complete authored stylesheet bundle
    rather than assuming every selector lives in one physical file.
    """
    seen: set[Path] = set()

    def visit(path: Path) -> list[str]:
        path = path.resolve()
        if path in seen:
            return []
        seen.add(path)
        text = path.read_text(encoding="utf-8")
        parts: list[str] = []
        for match in re.finditer(r"@import\s+[\"']([^\"']+)[\"']\s*;", text):
            import_path = match.group(1)
            if import_path.startswith(("http://", "https://")):
                continue
            parts.extend(visit(path.parent / import_path))
        parts.append(text)
        return parts

    return "\n".join(visit(entrypoint))
