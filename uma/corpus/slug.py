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

    def make(self, heading: str) -> str:
        # An empty slug is reserved for the intro section, so fall back to "section".
        return self.claim(slugify(heading) or "section")

    def claim(self, preferred: str) -> str:
        """Reserve `preferred`, or the first free `preferred-N` if it is taken."""
        base = preferred
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
