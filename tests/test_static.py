from tests.test_web import make_client

REQUIRED = [
    'id="question-form"', 'id="question-input"', 'id="mode-toggle"', 'id="columns"',
    'id="corpus-warning"', "column", "data-strategy", "answer", "status-badge", "metrics",
    "trace", "how-it-works", "stars", "data-stars", "reveal",
]


def test_index_has_required_elements(tmp_path):
    client, _ = make_client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    for needle in REQUIRED:
        assert needle in r.text, needle
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
