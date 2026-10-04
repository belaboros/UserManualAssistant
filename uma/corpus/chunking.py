"""Split sections into retrieval chunks."""

from uma.corpus.models import Chunk, Section

CHARS_PER_TOKEN = 4


def _split(text: str, max_chars: int) -> list[str]:
    """Pack paragraphs into pieces of at most max_chars; each later piece starts
    with the last paragraph of the previous piece."""
    paras = [p for p in text.split("\n\n") if p.strip()]
    pieces: list[list[str]] = []
    current: list[str] = []
    size = 0
    new_in_current = 0
    for para in paras:
        added = len(para) + (2 if current else 0)
        if current and new_in_current > 0 and size + added > max_chars:
            pieces.append(current)
            current = [current[-1]]
            size = len(current[0])
            new_in_current = 0
            added = len(para) + 2
        current.append(para)
        size += added
        new_in_current += 1
    if current:
        pieces.append(current)
    return ["\n\n".join(p) for p in pieces]


def chunk_sections(sections: list[Section], max_tokens: int = 400) -> list[Chunk]:
    max_chars = max_tokens * CHARS_PER_TOKEN
    chunks: list[Chunk] = []
    for s in sections:
        texts = [s.text] if len(s.text) <= max_chars else _split(s.text, max_chars)
        for i, t in enumerate(texts):
            chunks.append(Chunk(id=f"{s.id}#{i}", section_id=s.id, manual_id=s.manual_id, text=t, position=i))
    return chunks
