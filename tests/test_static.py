import re

from tests.test_web import make_client

REQUIRED = [
    'id="question-form"', 'id="question-input"', 'id="mode-toggle"', 'id="columns"',
    'id="corpus-warning"',
    'data-strategy="whole_context"', 'data-strategy="rag"', 'data-strategy="agentic"',
    'class="column"', 'class="answer"', 'class="status-badge"', 'class="metrics"',
    'class="trace"', 'class="how-it-works"', 'class="stars"', 'data-stars="1"',
    'data-stars="5"', 'class="reveal"', "<dialog", 'src="/static/app.js"',
]


def test_index_has_required_elements(tmp_path):
    client, _ = make_client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    for needle in REQUIRED:
        assert needle in r.text, needle
    assert r.text.count('class="column"') == 3
    assert r.text.count('data-stars="') == 15
    # No static label may name a strategy (would leak identity in blind mode).
    for tag in re.findall(r'<section class="column"[^>]*>', r.text):
        assert "aria-label=" not in tag, tag
        assert "aria-labelledby=" in tag, tag
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


LEADERBOARD_REQUIRED = [
    'id="mode-filter"', 'value="all"', 'value="blind"', 'value="labelled"',
    'id="leaderboard-table"', 'id="recent-table"', 'id="export-csv"', 'id="reset-votes"',
    'href="/api/export.csv"', 'href="/"', 'href="/leaderboard"',
    'src="/static/leaderboard.js"', 'href="/static/style.css"',
]


def test_leaderboard_page_has_required_elements(tmp_path):
    client, _ = make_client(tmp_path)
    r = client.get("/leaderboard")
    assert r.status_code == 200
    for needle in LEADERBOARD_REQUIRED:
        assert needle in r.text, needle
    assert client.get("/static/leaderboard.js").status_code == 200
    # The ask page links to the leaderboard too.
    assert 'href="/leaderboard"' in client.get("/").text


def test_cdn_scripts_are_pinned_with_sri(tmp_path):
    client, _ = make_client(tmp_path)
    for page in ("/", "/leaderboard"):
        html = client.get(page).text
        for tag in re.findall(r"<script[^>]*\bsrc=\"https?://[^>]*>", html):
            src = re.search(r'src="([^"]+)"', tag).group(1)
            assert re.search(r"@\d+\.\d+\.\d+/", src), f"not pinned to an exact version: {src}"
            assert re.search(r'integrity="sha384-[A-Za-z0-9+/=]{64}"', tag), f"no SRI: {src}"
            assert 'crossorigin="anonymous"' in tag, src
    assert "marked@12.0.2/marked.min.js" in client.get("/").text
