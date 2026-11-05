"""Load knowledge-base articles (Markdown with a small front-matter block) and split them into chunks."""

from __future__ import annotations

import re
from pathlib import Path

from .schemas import Chunk

_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def parse_article(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(raw)
    if not match:
        raise ValueError(f"{path.name}: missing front matter")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    for required in ("id", "category", "title"):
        if required not in meta:
            raise ValueError(f"{path.name}: front matter is missing '{required}'")
    return meta, raw[match.end():]


def chunk_article(meta: dict[str, str], body: str) -> list[Chunk]:
    """One chunk per '## ' section. Sections are short, so they make natural retrieval units."""
    chunks: list[Chunk] = []
    for block in re.split(r"^## ", body, flags=re.MULTILINE)[1:]:
        heading, _, text = block.partition("\n")
        text = text.strip()
        if text:
            chunks.append(
                Chunk(
                    article_id=meta["id"],
                    title=meta["title"],
                    category=meta["category"],
                    section=heading.strip(),
                    text=text,
                )
            )
    return chunks


def load_kb(kb_dir: Path) -> list[Chunk]:
    paths = sorted(kb_dir.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"No knowledge-base articles found in {kb_dir}")
    chunks: list[Chunk] = []
    for path in paths:
        meta, body = parse_article(path)
        chunks.extend(chunk_article(meta, body))
    return chunks


def article_steps(chunks: list[Chunk], article_id: str) -> str:
    """The 'Quick fix' or 'What to do immediately' section of an article, used for self-serve answers."""
    for chunk in chunks:
        if chunk.article_id == article_id and chunk.section in ("Quick fix", "What to do immediately"):
            return chunk.text
    return ""
