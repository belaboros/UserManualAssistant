from selectolax.lexbor import LexborHTMLParser, LexborNode

from uma.corpus.models import Section
from uma.corpus.slug import UniqueAnchors, section_id, source_url

_BOILERPLATE = "nav, header, footer, aside, script, style, noscript"
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = {"p", "li", "pre", "td", "th", "dt", "dd", "blockquote"}
_BLOCK_SELECTOR = ", ".join(sorted(_BLOCKS))


def _has_blocks(node: LexborNode) -> bool:
    return any(n.mem_id != node.mem_id for n in node.css(_BLOCK_SELECTOR))


def _inside_block(node: LexborNode) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tag in _BLOCKS:
            return True
        parent = parent.parent
    return False


def _block_lines(node: LexborNode) -> list[str]:
    """One line per block: a container's own text, then its nested blocks' lines."""
    if node.tag == "pre":
        text = (node.text() or "").strip()
        return [text] if text else []
    lines: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        line = " ".join(" ".join(buf).split())
        if line:
            lines.append(line)
        buf.clear()

    def walk(parent: LexborNode) -> None:
        for child in parent.iter(include_text=True):
            if child.tag == "-text":
                buf.append(child.text() or "")
            elif child.tag in _BLOCKS:
                flush()
                lines.extend(_block_lines(child))
            elif _has_blocks(child):
                flush()
                walk(child)
            else:
                buf.append(child.text(separator=" ") or "")

    walk(node)
    flush()
    return lines


def parse_html(
    html: str,
    *,
    manual_id: str,
    doc_path: str,
    base_url: str | None,
    start_position: int = 0,
) -> list[Section]:
    """Split HTML into one Section per heading that has body text.

    Same semantics as parse_markdown: text before the first heading becomes an
    intro section (anchor ""). Navigation and other boilerplate is dropped.
    """
    tree = LexborHTMLParser(html)
    for node in tree.css(_BOILERPLATE):
        node.decompose()
    root = tree.css_first("main") or tree.css_first("article") or tree.body
    if root is None:
        return []

    anchors = UniqueAnchors()
    # Each entry: [level, title, anchor, body_lines]; the intro is level 0.
    blocks: list[list] = [[0, "", "", []]]
    for node in root.traverse():
        tag = node.tag
        if tag in _HEADINGS:
            title = " ".join((node.text(separator=" ") or "").split())
            existing = node.attributes.get("id")
            if existing:
                anchor = anchors.claim(existing)
            else:
                anchor = anchors.make(title)
            blocks.append([int(tag[1:]), title, anchor, []])
        elif tag in _BLOCKS and not _inside_block(node):
            blocks[-1][3].extend(_block_lines(node))

    sections: list[Section] = []
    position = start_position
    stack: list[tuple[int, str]] = []
    for level, title, anchor, lines in blocks:
        if level:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        body = "\n".join(lines).strip()
        if not body:
            continue
        sections.append(Section(
            id=section_id(manual_id, doc_path, anchor),
            manual_id=manual_id, doc_path=doc_path,
            heading_path=tuple(t for _, t in stack),
            anchor=anchor, text=body, position=position,
            source_url=source_url(base_url, doc_path, anchor),
        ))
        position += 1
    return sections
