"""Score how strongly two incidents are linked, and explain why.

Linkage logic mirrors how analysts reason about it:
  * A shared *rare* descriptive signature (same unusual trigger + container +
    TTP) is strong evidence of a common builder. Common features (everything is
    an IED) carry little weight. We capture this with an IDF-style weight per
    feature: weight = log(N / doc_freq).
  * A shared *identity* — the same phone number or named individual across two
    incidents — is a strong network link on its own, even with few shared
    features.
  * Same/near location and time nudge the score but never carry it alone.

Output is a Link with a 0..1 score and a human-readable rationale.
"""
from __future__ import annotations

import math
from collections import Counter
from itertools import combinations

from rapidfuzz import fuzz

from .models import Incident, Link


class Matcher:
    def __init__(
        self,
        w_features: float = 0.7,
        w_location: float = 0.15,
        entity_bonus: float = 0.5,   # per shared strong identity, before cap
        loc_fuzz_threshold: int = 88,
        name_fuzz_threshold: int = 90,
    ):
        self.w_features = w_features
        self.w_location = w_location
        self.entity_bonus = entity_bonus
        self.loc_fuzz_threshold = loc_fuzz_threshold
        self.name_fuzz_threshold = name_fuzz_threshold
        self.weights: dict[tuple[str, str], float] = {}

    # -- corpus statistics ---------------------------------------------------
    def fit(self, incidents: list[Incident]) -> "Matcher":
        n = max(len(incidents), 1)
        df: Counter = Counter()
        for inc in incidents:
            for k in inc.feature_keys():
                df[k] += 1
        # Smoothed IDF so a feature shared by all still has a small positive wt.
        self.weights = {k: math.log((n + 1) / (c + 0.5)) + 0.1 for k, c in df.items()}
        return self

    def _weight(self, key) -> float:
        return self.weights.get(key, 1.0)

    # -- fuzzy entity overlap ------------------------------------------------
    @staticmethod
    def _fuzzy_overlap(a: set[str], b: set[str], threshold: int) -> list[str]:
        shared = []
        for x in a:
            for y in b:
                if x == y or fuzz.token_sort_ratio(x, y) >= threshold:
                    shared.append(x if x == y else f"{x}~{y}")
                    break
        return shared

    # -- pairwise score ------------------------------------------------------
    def score(self, a: Incident, b: Incident) -> Link:
        ka, kb = a.feature_keys(), b.feature_keys()
        shared_keys = ka & kb
        union_keys = ka | kb

        num = sum(self._weight(k) for k in shared_keys)
        den = sum(self._weight(k) for k in union_keys) or 1.0
        weighted_jaccard = num / den
        plain_jaccard = len(shared_keys) / (len(union_keys) or 1)
        # Blend: rarity term rewards distinctive shared signatures in large
        # corpora; the coverage term keeps small-corpus matches meaningful.
        feature_sim = 0.5 * weighted_jaccard + 0.5 * plain_jaccard

        reasons: list[str] = []
        shared_features = [f"{f}={v}" for (f, v) in sorted(shared_keys)]
        if shared_features:
            top = sorted(shared_keys, key=self._weight, reverse=True)[:3]
            reasons.append(
                "shared signature: " + ", ".join(f"{f}={v}" for f, v in top)
            )

        # Strong identities.
        shared_entities: list[str] = []
        phones = a.phones & b.phones
        if phones:
            shared_entities += [f"phone:{p}" for p in sorted(phones)]
            reasons.append(f"same phone number ({', '.join(sorted(phones))})")
        persons = self._fuzzy_overlap(a.persons, b.persons, self.name_fuzz_threshold)
        if persons:
            shared_entities += [f"person:{p}" for p in persons]
            reasons.append(f"same individual ({', '.join(persons)})")
        groups = self._fuzzy_overlap(a.groups, b.groups, self.name_fuzz_threshold)
        if groups:
            shared_entities += [f"group:{g}" for g in groups]
            reasons.append(f"same group ({', '.join(groups)})")

        entity_component = min(self.entity_bonus * len(shared_entities), 0.6)

        # Location similarity (soft).
        loc_sim = 0.0
        la, lb = (a.location or ""), (b.location or "")
        if la and lb:
            r = fuzz.token_sort_ratio(la, lb)
            if r >= self.loc_fuzz_threshold:
                loc_sim = 1.0
                reasons.append(f"same/near location ({la} ~ {lb})")

        score = min(
            self.w_features * feature_sim
            + entity_component
            + self.w_location * loc_sim,
            1.0,
        )
        return Link(
            a=a.incident_id,
            b=b.incident_id,
            score=round(score, 3),
            shared_features=shared_features,
            shared_entities=shared_entities,
            reasons=reasons,
        )

    def all_pairs(self, incidents: list[Incident], threshold: float = 0.25) -> list[Link]:
        links = []
        for a, b in combinations(incidents, 2):
            link = self.score(a, b)
            if link.score >= threshold and (link.shared_features or link.shared_entities):
                links.append(link)
        links.sort(key=lambda l: l.score, reverse=True)
        return links
