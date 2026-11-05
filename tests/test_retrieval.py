import pytest

from fixflow.kb import load_kb
from fixflow.retrieval import BM25, Retriever, tokenize_v1, tokenize_v2


@pytest.fixture(scope="module")
def chunks(request):
    from fixflow.config import Settings

    return load_kb(Settings().kb_dir)


def test_kb_loads_every_article(chunks):
    assert len({c.article_id for c in chunks}) == 12
    assert all(c.text and c.section for c in chunks)


def test_tokenizers():
    assert tokenize_v1("The Battery is NOT charging!") == ["battery", "charging"]
    assert "charg" in tokenize_v2("charging")
    assert "liquid" in tokenize_v2("I spilled coffee")


def test_bm25_prefers_rare_matching_terms():
    bm25 = BM25([["battery", "charge"], ["screen", "flicker"], ["battery", "drain", "battery"]])
    scores = bm25.scores(["flicker"])
    assert list(scores) == [1]


def test_bm25_ignores_unknown_terms():
    assert BM25([["a", "b"]]).scores(["zzz"]) == {}


@pytest.mark.parametrize(
    "query,expected",
    [
        ("battery stuck at 80 percent", "KB-001"),
        ("screen flickering", "KB-004"),
        ("wifi keeps disconnecting", "KB-006"),
        ("forgot my password account locked", "KB-010"),
    ],
)
def test_search_finds_the_right_article(chunks, query, expected):
    hits = Retriever(chunks, "v2").search_articles(query, k=3)
    assert hits[0].chunk.article_id == expected


def test_search_articles_returns_distinct_articles(chunks):
    hits = Retriever(chunks).search_articles("battery", k=3)
    ids = [h.chunk.article_id for h in hits]
    assert len(ids) == len(set(ids))


def test_invalid_version(chunks):
    with pytest.raises(ValueError):
        Retriever(chunks, "v9")
