"""Information scent: how much a link looks like it leads to the goal.

M-004 showed the choice channel carries the entire measured gate effect, and
choice is `scent x visibility`. So this module is the load-bearing half of the
instrument, and until now it was a word-overlap ratio that could only ever
return 0.0 or 1.0.

That binary output is why the vocabulary-gap case gives no signal (D-007): a
goal phrased the way a user would phrase it shares no words with the labels, so
every score is 0, softmax is uniform, and visibility has nothing to modulate.
Embedding scent exists to give the gate something to weight.

Two implementations, chosen with --scent:

    keyword     set overlap. Fast, no dependency, deliberately stupid.
    embedding   cosine similarity of sentence-transformer encodings.

Both return [0,1] per element and are pure functions of (goal, element text), so
they are cached and reproducible.
"""
from __future__ import annotations

import re

STOPWORDS = {
    "a", "an", "the", "i", "my", "me", "we", "it", "this", "that", "these",
    "is", "are", "was", "be", "been", "can", "could", "do", "does", "did",
    "to", "of", "for", "in", "on", "at", "by", "with", "and", "or", "but",
    "if", "so", "as", "from", "up", "out", "am", "want", "need", "would",
    "like", "how", "what", "where", "there", "here", "you", "your", "again",
}

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in STOPWORDS and len(w) > 2}


def element_text(element: dict) -> str:
    """What the visitor reads off a link. Name first, href as weak extra signal."""
    return " ".join(filter(None, [element.get("name"), element.get("href")]))


class KeywordScent:
    """Word overlap between the goal and the element's visible text.

    Deliberately stupid, and kept as the default so the project runs with no
    model download. Its output is quantised to multiples of 1/|goal words|, so
    on a short goal there are only a handful of reachable values — and for a
    goal phrased in the user's own vocabulary the overlap is 0 for *every*
    element on the page, which is the flat-scent case in D-007.
    """

    name = "keyword"

    def score(self, goal: str, elements: list[dict]) -> list[float]:
        g = tokens(goal)
        if not g:
            return [0.0] * len(elements)
        out = []
        for el in elements:
            e = tokens(element_text(el))
            out.append(len(g & e) / len(g) if e else 0.0)
        return out


class EmbeddingScent:
    """Cosine similarity between goal and element encodings.

    Continuous, so a link can be *somewhat* promising — which is the property
    the visibility gate needs in order to do any work at all.

    Negative cosines are clamped to 0: "actively unrelated" and "unrelated" are
    the same thing to a visitor, and letting them go negative would invert the
    gate (multiplying by visibility would make a faint irrelevant link score
    HIGHER than a prominent irrelevant one).
    """

    name = "embedding"
    binary = False

    def __init__(self, model: str = DEFAULT_MODEL):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:      # pragma: no cover - depends on environment
            raise ImportError(
                "embedding scent needs sentence-transformers:\n"
                "    pip install sentence-transformers\n"
                "or run with --scent keyword"
            ) from e
        self.model_name = model
        self._model = SentenceTransformer(model)
        self._cache: dict[str, object] = {}

    def _encode(self, texts: list[str]):
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            vecs = self._model.encode(missing, normalize_embeddings=True,
                                      show_progress_bar=False)
            self._cache.update(zip(missing, vecs))
        return [self._cache[t] for t in texts]

    def score(self, goal: str, elements: list[dict]) -> list[float]:
        if not goal.strip() or not elements:
            return [0.0] * len(elements)
        texts = [element_text(el) for el in elements]
        gv = self._encode([goal])[0]
        out = []
        for el, v in zip(elements, self._encode(texts)):
            if not element_text(el).strip():
                out.append(0.0)
                continue
            # both are unit vectors, so the dot product is the cosine
            out.append(max(0.0, min(1.0, float(gv @ v))))
        return out


DEFAULT = KeywordScent()


def get(name: str, model: str = DEFAULT_MODEL):
    if name == "keyword":
        return KeywordScent()
    if name == "embedding":
        return EmbeddingScent(model)
    raise ValueError(f"unknown scent model {name!r}; expected keyword or embedding")
