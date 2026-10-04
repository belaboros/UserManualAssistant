import re
from pathlib import PurePosixPath


def slugify(heading: str) -> str:
    """GitHub-style anchor slug."""
    kept = re.sub(r"[^\w \-]", "", heading.lower())
    return kept.replace(" ", "-")


class UniqueAnchors:
    """Hands out slugs, suffixing repeats with -1, -2, ..."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def register(self, anchor: str) -> None:
        """Reserve an anchor that already exists in the source document."""
        if anchor:
            self._seen.add(anchor)

    def make(self, heading: str) -> str:
        # An empty slug is reserved for the intro section, so fall back to "section".
        base = slugify(heading) or "section"
        slug, n = base, 0
        while slug in self._seen:
            n += 1
            slug = f"{base}-{n}"
        self._seen.add(slug)
        return slug


def section_id(manual_id: str, doc_path: str, anchor: str) -> str:
    """Section id; uses doc_path without extension so same-named files in folders differ."""
    stem = str(PurePosixPath(doc_path).with_suffix(""))
    return f"{manual_id}:{stem}:{anchor or 'intro'}"


def source_url(base_url: str | None, doc_path: str, anchor: str) -> str | None:
    if not base_url:
        return None
    url = f"{base_url.rstrip('/')}/{doc_path}"
    return f"{url}#{anchor}" if anchor else url
