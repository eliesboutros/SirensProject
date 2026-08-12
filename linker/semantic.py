"""Meaning-based matching — the offline 'AI' upgrade.

The taxonomy matcher (match.py) is precise but literal: it links two reports when
they share the *same normalised feature*. This layer complements it by comparing
the *meaning* of the free-text narratives, so a link is still found when two
analysts describe the same thing in different words
("IED buried in the road" vs "device concealed beneath the route surface").

It uses spaCy word vectors, which run entirely on your machine — no internet, no
API key, no per-use cost. Vectors ship in the medium/large English models, so if
only the small model (no vectors) is installed we fall back to a robust
token-overlap similarity and say so, rather than crashing.

    pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl
"""
from __future__ import annotations

import math

from rapidfuzz import fuzz

from .models import Incident

_NLP = None
_MODE = None  # "vectors:<model>" or "lexical"


def _try_load():
    global _NLP, _MODE
    if _MODE is not None:
        return
    import spacy
    for name in ("en_core_web_lg", "en_core_web_md"):
        try:
            nlp = spacy.load(name, disable=["ner", "parser", "lemmatizer"])
            if nlp.vocab.vectors_length > 0:
                _NLP, _MODE = nlp, f"vectors:{name}"
                return
        except Exception:
            continue
    # No vector model available — use a lexical fallback so nothing breaks.
    _NLP, _MODE = None, "lexical"


def mode() -> str:
    """Return the active similarity mode: 'vectors:<model>' or 'lexical'."""
    _try_load()
    return _MODE


def has_vectors() -> bool:
    return mode().startswith("vectors")


def _vec(text: str):
    """Content-word average vector for a narrative.

    Averaging *every* token (incl. stopwords/punctuation) washes out meaning on
    short, same-domain reports so everything looks ~0.85 similar. Restricting to
    content words (drop stopwords, punctuation, non-alphabetic) keeps the
    distinctive terms and gives an informative spread between related and
    unrelated reports.
    """
    import numpy as np
    doc = _NLP(text or "")
    toks = [t for t in doc if t.has_vector and not t.is_stop and not t.is_punct and t.is_alpha]
    if not toks:
        return None
    return np.mean([t.vector for t in toks], axis=0)


def _cosine(u, v) -> float:
    import numpy as np
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu == 0 or nv == 0:
        return 0.0
    return float(np.dot(u, v) / (nu * nv))


def _lexical(a: str, b: str) -> float:
    a, b = a or "", b or ""
    return (0.5 * fuzz.token_set_ratio(a, b) + 0.5 * fuzz.token_sort_ratio(a, b)) / 100.0


def _blend(cos: float, lex: float) -> float:
    """Meaning (word vectors) leads; distinctive-term overlap sharpens it."""
    return round(max(0.0, min(1.0, 0.65 * max(0.0, cos) + 0.35 * lex)), 4)


def similarity(text_a: str, text_b: str) -> float:
    """Semantic similarity of two narratives in [0, 1]."""
    _try_load()
    lex = _lexical(text_a, text_b)
    if _MODE.startswith("vectors"):
        va, vb = _vec(text_a), _vec(text_b)
        if va is not None and vb is not None:
            return _blend(_cosine(va, vb), lex)
    return round(lex, 4)


class SemanticIndex:
    """Precompute narrative representations for a corpus and rank by meaning."""

    def __init__(self, incidents: list[Incident]):
        _try_load()
        self.incidents = incidents
        self._vecs = {}
        if has_vectors():
            for inc in incidents:
                v = _vec(inc.narrative)
                if v is not None:
                    self._vecs[inc.incident_id] = v

    def top_matches(self, query: str, k: int = 5, exclude_id: str | None = None):
        """Return up to k (incident, similarity) pairs most similar in meaning."""
        scored = []
        qv = _vec(query) if has_vectors() else None
        for inc in self.incidents:
            if exclude_id and inc.incident_id == exclude_id:
                continue
            if qv is not None and inc.incident_id in self._vecs:
                s = _blend(_cosine(qv, self._vecs[inc.incident_id]),
                           _lexical(query, inc.narrative))
            else:
                s = similarity(query, inc.narrative)
            scored.append((inc, round(s, 4)))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]
