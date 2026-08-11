"""Area / object query -> a record-based pre-arrival brief.

Given a location (and optionally a free-text description of what a responder is
looking at), this returns what the HISTORICAL RECORD says about that place:
which object types have been reported there, how often and how recently, the
device signature they tend to co-occur with, and the past incidents that best
match the description — each with its source id and any reference photo.

Hard boundary: this retrieves and ranks *past reporting*. It never identifies
the object in front of the responder and never offers handling/render-safe
guidance. A qualified specialist confirms every identification.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from rapidfuzz import fuzz

from .models import Incident
from .match import Matcher

# Facets that describe the observed object (as opposed to the attack method).
OBJECT_FACETS = {"object_type", "colour", "shape", "condition", "fuze", "size"}
# Facets that describe how the device was employed (the co-occurring signature).
SIGNATURE_FACETS = {"initiation", "trigger", "emplacement", "container", "charge_label", "ttp"}


@dataclass
class Match:
    incident_id: str
    score: float
    location: str
    date: str | None
    object_features: list[str]
    shared: list[str]
    photo: str | None


@dataclass
class Brief:
    location_query: str
    describe_query: str | None
    n_in_area: int
    object_profile: list[tuple[str, int, str | None]]   # (object_type, count, most_recent_date)
    area_signature: list[str]                            # common co-occurring device features
    matches: list[Match] = field(default_factory=list)
    responder_photo: str | None = None
    note: str = ("RECORD-BASED PRE-ARRIVAL BRIEF. This is retrieval from past reporting, "
                 "not identification of the present object and not handling guidance. "
                 "A qualified specialist confirms all identifications.")


def _in_area(inc: Incident, location: str, threshold: int = 80) -> bool:
    cand = [inc.location or ""] + list(inc.places)
    for c in cand:
        if c and fuzz.token_sort_ratio(c.lower(), location.lower()) >= threshold:
            return True
    # Grid prefix match (same 100km square) as a coarse geographic fallback.
    return False


def area_brief(
    incidents: list[Incident],
    location: str,
    describe: str | None = None,
    extractor=None,
    responder_photo: str | None = None,
    top: int = 5,
) -> Brief:
    sel = [i for i in incidents if _in_area(i, location)]

    # Object profile: which object types have been reported here, count, recency.
    counts: Counter = Counter()
    recent: dict[str, str] = {}
    for i in sel:
        for f in i.features:
            if f.facet == "object_type":
                counts[f.value] += 1
                if i.date and (f.value not in recent or i.date > recent[f.value]):
                    recent[f.value] = i.date
    object_profile = [(t, c, recent.get(t)) for t, c in counts.most_common()]

    # Area device signature: most common co-occurring employment features.
    sig_counts: Counter = Counter()
    for i in sel:
        for f in i.features:
            if f.facet in SIGNATURE_FACETS:
                sig_counts[f"{f.facet}={f.value}"] += 1
    need = max(2, int(len(sel) * 0.5)) if len(sel) > 1 else 1
    area_signature = [k for k, c in sig_counts.most_common() if c >= need]

    # Description matching: rank the area's incidents by similarity to the
    # responder's description (object attributes dominate).
    matches: list[Match] = []
    pool = sel or incidents
    if describe and extractor and pool:
        q = extractor.extract(Incident(incident_id="QUERY", narrative=describe))
        m = Matcher().fit(pool)
        scored = []
        for i in pool:
            link = m.score(q, i)
            # Restrict the "why" to object-facet overlap for a responder view.
            obj_shared = [s for s in link.shared_features
                          if s.split("=")[0] in OBJECT_FACETS]
            if obj_shared:
                scored.append((link.score, obj_shared, i))
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, shared, i in scored[:top]:
            matches.append(Match(
                incident_id=i.incident_id,
                score=round(score, 3),
                location=i.location or "",
                date=i.date,
                object_features=[f"{f.facet}={f.value}" for f in i.features
                                 if f.facet in OBJECT_FACETS],
                shared=shared,
                photo=i.photo,
            ))

    return Brief(
        location_query=location,
        describe_query=describe,
        n_in_area=len(sel),
        object_profile=object_profile,
        area_signature=area_signature,
        matches=matches,
        responder_photo=responder_photo,
    )
