import re


def slugify(heading: str) -> str:
    """GitHub-style anchor slug."""
    kept = re.sub(r"[^\w \-]", "", heading.lower())
    return kept.replace(" ", "-")


class UniqueAnchors:
    """Hands out slugs, suffixing repeats with -1, -2, ..."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def make(self, heading: str) -> str:
        base = slugify(heading)
        slug, n = base, 0
        while slug in self._seen:
            n += 1
            slug = f"{base}-{n}"
        self._seen.add(slug)
        return slug
