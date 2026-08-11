"""Data models for the C-IED link-analysis pipeline.

An Incident is the unit of analysis. Everything the pipeline learns about it —
extracted features, who/where/when — hangs off the Incident so that a link back
to source is always available (explainability is the whole point).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Feature:
    """One normalized (facet, value) observation, e.g. ('trigger','pressure_plate').

    `surface` keeps the exact text it was lifted from, so an analyst can audit
    why the tool assigned the canonical value.
    """
    facet: str
    value: str
    surface: str = ""

    def key(self) -> tuple[str, str]:
        return (self.facet, self.value)

    def __str__(self) -> str:
        return f"{self.facet}={self.value}"


@dataclass
class Incident:
    incident_id: str
    date: str | None = None
    location: str | None = None          # canonical/primary place name
    grid: str | None = None              # MGRS or lat/long if present
    narrative: str = ""
    photo: str | None = None             # reference/filename of an attached image (NOT analyzed)
    # Extracted, normalized descriptive features (device/emplacement/ttp).
    features: list[Feature] = field(default_factory=list)
    # Free entities pulled from text.
    persons: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    places: set[str] = field(default_factory=set)

    def feature_keys(self) -> set[tuple[str, str]]:
        return {f.key() for f in self.features}

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["persons"] = sorted(self.persons)
        d["groups"] = sorted(self.groups)
        d["phones"] = sorted(self.phones)
        d["places"] = sorted(self.places)
        d["features"] = [f"{f.facet}={f.value}" for f in self.features]
        d["photo"] = self.photo
        return d


@dataclass
class Link:
    """A scored, explained relationship between two incidents."""
    a: str
    b: str
    score: float
    shared_features: list[str] = field(default_factory=list)
    shared_entities: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Cluster:
    """A group of incidents the tool believes share a signature/network."""
    cluster_id: str
    members: list[str] = field(default_factory=list)
    signature: list[str] = field(default_factory=list)  # features common to the group
    internal_links: list[Link] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.members)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "size": self.size,
            "members": self.members,
            "signature": self.signature,
            "internal_links": [l.to_dict() for l in self.internal_links],
        }
