from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def test_markdown_relative_links_resolve() -> None:
    broken: list[str] = []
    markdown_files = (
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "THIRD_PARTY_NOTICES.md",
        *(PROJECT_ROOT / "docs").glob("*.md"),
        *(PROJECT_ROOT / "packaging").rglob("*.md"),
    )
    for document in markdown_files:
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                broken.append(
                    f"{document.relative_to(PROJECT_ROOT)} -> {raw_target}"
                )
    assert broken == []


def test_repository_layout_keeps_generated_artifacts_outside_tracked_docs() -> None:
    layout = (PROJECT_ROOT / "docs" / "repository-layout.md").read_text(
        encoding="utf-8"
    )
    assert "data/packaging-manifests/" in layout
    assert "data/course-delivery/" in layout
    assert "dist/installer-offline/" in layout
    assert "GigaAM Multilingual Large CTC" in layout
    assert "C:\\Users\\" not in layout
