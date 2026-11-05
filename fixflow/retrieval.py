"""Retrieval built from scratch: tokenizer, BM25 ranking and an inverted index. No vector database.

Two versions are kept on purpose so the evaluation can compare them:
  v1  plain lowercase word tokens, chunk text only (the baseline)
  v2  light stemming, a small domain synonym map, and the article title indexed with each chunk
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from .schemas import Chunk, SearchHit

STOPWORDS = frozenset(
    """a an and are as at be but by can do does for from has have i if in into is it its me my no not
    of on or so that the their then there this to was were what when where which while who why will with
    you your just like now also very really any all some get got been am im ive dont doesnt cant""".split()
)

# Words users write mapped to words the manuals use. Built from failures on the dev split only.
SYNONYMS: dict[str, list[str]] = {
    # Added after dev ticket T012 ("I spilled coffee on my keyboard") missed the liquid-damage article.
    "coffee": ["liquid", "damage"],
    "spill": ["liquid", "damage"],
}

_TOKEN = re.compile(r"[a-z0-9]+")


def _stem(word: str) -> str:
    """A deliberately small suffix stripper. Good enough for short support text, easy to explain."""
    for suffix in ("ingly", "ing", "edly", "ed", "ies", "es", "s", "ly"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    return word


def tokenize_v1(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def tokenize_v2(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(text.lower().replace("-", "").replace("'", "")):
        if raw in STOPWORDS:
            continue
        stem = _stem(raw)
        tokens.append(stem)
        for key in (raw, stem):
            if key in SYNONYMS:
                tokens.extend(SYNONYMS[key])
                break
    return tokens


class BM25:
    """Okapi BM25 over a list of token lists. k1 controls term-frequency saturation, b length normalisation."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.doc_freqs = [Counter(doc) for doc in docs]
        self.doc_lens = [len(doc) for doc in docs]
        self.avg_len = sum(self.doc_lens) / max(len(docs), 1)
        df: dict[str, int] = defaultdict(int)
        self.index: dict[str, list[int]] = defaultdict(list)  # inverted index: term -> doc ids
        for doc_id, freqs in enumerate(self.doc_freqs):
            for term in freqs:
                df[term] += 1
                self.index[term].append(doc_id)
        n = len(docs)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    def scores(self, query: list[str]) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for doc_id in self.index[term]:
                tf = self.doc_freqs[doc_id][term]
                norm = tf + self.k1 * (1 - self.b + self.b * self.doc_lens[doc_id] / self.avg_len)
                out[doc_id] += idf * tf * (self.k1 + 1) / norm
        return out


class Retriever:
    def __init__(self, chunks: list[Chunk], version: str = "v2") -> None:
        if version not in ("v1", "v2"):
            raise ValueError("version must be 'v1' or 'v2'")
        self.chunks = chunks
        self.version = version
        self.tokenize = tokenize_v2 if version == "v2" else tokenize_v1
        docs = [self.tokenize(self._doc_text(c)) for c in chunks]
        self.bm25 = BM25(docs)

    def _doc_text(self, chunk: Chunk) -> str:
        if self.version == "v1":
            return chunk.text
        # v2: index the title twice with every chunk (a simple field boost) plus the section name.
        return f"{chunk.title} {chunk.title} {chunk.section} {chunk.text}"

    def search(self, query: str, k: int = 3) -> list[SearchHit]:
        scored = self.bm25.scores(self.tokenize(query))
        ranked = sorted(scored.items(), key=lambda item: item[1], reverse=True)[:k]
        return [SearchHit(chunk=self.chunks[i], score=round(s, 4)) for i, s in ranked]

    def search_articles(self, query: str, k: int = 3) -> list[SearchHit]:
        """Best chunk per article, so the top-k is k different articles rather than k sections of one."""
        best: dict[str, SearchHit] = {}
        for hit in self.search(query, k=len(self.chunks)):
            if hit.chunk.article_id not in best:
                best[hit.chunk.article_id] = hit
        return list(best.values())[:k]
