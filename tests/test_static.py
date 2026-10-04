import re

from tests.test_web import make_client

REQUIRED = [
    'id="question-form"', 'id="question-input"', 'id="mode-toggle"', 'id="columns"',
    'id="corpus-warning"',
    'data-strategy="baseline"', 'data-strategy="whole_context"', 'data-strategy="rag"', 'data-strategy="agentic"',
    'data-strategy="agentic_web"',
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
    assert r.text.count('class="column"') == 5
    assert r.text.count('data-stars="') == 25
    # The baseline column comes first (leftmost).
    order = re.findall(r'<section class="column" data-strategy="([a-z_]+)"', r.text)
    assert order == ["baseline", "whole_context", "rag", "agentic", "agentic_web"]
    assert 'aria-labelledby="title-baseline"' in r.text
    # No static label may name a strategy (would leak identity in blind mode).
    for tag in re.findall(r'<section class="column"[^>]*>', r.text):
        assert "aria-label=" not in tag, tag
        assert "aria-labelledby=" in tag, tag
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_columns_have_maximize_toggle(tmp_path):
    client, _ = make_client(tmp_path)
    html = client.get("/").text
    sections = re.findall(r'<section class="column".*?</section>', html, re.S)
    assert len(sections) == 5
    for sec in sections:
        buttons = re.findall(r'<button[^>]*class="maximize"[^>]*>', sec)
        assert len(buttons) == 1, sec[:80]
        assert 'aria-label="' in buttons[0], buttons[0]
        assert 'aria-pressed="false"' in buttons[0], buttons[0]
        sid = re.search(r'data-strategy="([a-z_]+)"', sec).group(1)
        assert f'id="badge-{sid}"' in sec, sid
        assert f'aria-describedby="title-{sid} badge-{sid}"' in buttons[0], buttons[0]
    js = client.get("/static/app.js").text
    assert "dataset.maximized" in js
    assert "matchMedia" in js  # maximized state is cleared below 700px
    css = client.get("/static/style.css").text
    assert "data-maximized" in css


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


def test_web_citation_markup_is_safe(tmp_path):
    client, _ = make_client(tmp_path)
    js = client.get("/static/app.js").text
    assert 'rel = "noopener noreferrer"' in js
    assert '"_blank"' in js
    assert "https?:" in js  # only http(s) URLs become links
    css = client.get("/static/style.css").text
    assert "blockquote.conflict" in css


def test_conflict_regex_accepts_emoji_variation(tmp_path):
    client, _ = make_client(tmp_path)
    js = client.get("/static/app.js").text
    pattern = re.search(r"if \(/(.*Conflict)/\.test\(bq\.textContent\)\)", js).group(1)
    for prefix in ("⚠ Conflict", "⚠️ Conflict", "  ⚠️  Conflict"):
        assert re.match(pattern, prefix), prefix
    assert not re.match(pattern, "Conflict")
    assert '" web search"' in js and '" web searches"' in js


def test_ask_page_uses_full_width_leaderboard_keeps_cap(tmp_path):
    client, _ = make_client(tmp_path)
    assert '<main class="wide">' in client.get("/").text
    assert '<main>' in client.get("/leaderboard").text
    css = client.get("/static/style.css").text
    assert re.search(r"main\.wide\s*\{[^}]*max-width:\s*none", css)
    assert re.search(r"(?m)^main\s*\{[^}]*max-width:\s*1400px", css)
