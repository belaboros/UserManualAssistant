from markdown_it import MarkdownIt

from uma.corpus.models import Section
from uma.corpus.slug import UniqueAnchors, section_id, source_url


def parse_markdown(
    text: str,
    *,
    manual_id: str,
    doc_path: str,
    base_url: str | None,
    start_position: int = 0,
) -> list[Section]:
    """Split Markdown into one Section per heading that has body text.

    Text before the first heading becomes an intro section (anchor "").
    """
    lines = text.splitlines()
    tokens = MarkdownIt("commonmark").parse(text)
    anchors = UniqueAnchors()

    # (level, title, anchor, heading_start_line, body_start_line) per heading
    headings: list[tuple[int, str, str, int, int]] = []
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            title = tokens[i + 1].content
            headings.append((int(tok.tag[1:]), title, anchors.make(title), tok.map[0], tok.map[1]))

    sections: list[Section] = []
    position = start_position

    def emit(path: tuple[str, ...], anchor: str, start: int, end: int) -> None:
        nonlocal position
        body = "\n".join(lines[start:end]).strip()
        if not body:
            return
        sections.append(Section(
            id=section_id(manual_id, doc_path, anchor),
            manual_id=manual_id, doc_path=doc_path, heading_path=path,
            anchor=anchor, text=body, position=position,
            source_url=source_url(base_url, doc_path, anchor),
        ))
        position += 1

    first_start = headings[0][3] if headings else len(lines)
    emit((), "", 0, first_start)

    stack: list[tuple[int, str]] = []
    for n, (level, title, anchor, _, body_start) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = headings[n + 1][3] if n + 1 < len(headings) else len(lines)
        emit(tuple(t for _, t in stack), anchor, body_start, end)
    return sections
