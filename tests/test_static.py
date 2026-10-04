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
