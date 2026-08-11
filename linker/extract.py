"""Extract normalized features and entities from each incident narrative.

Three complementary passes:
  1. Taxonomy gazetteer  -> canonical descriptive features (facet=value).
  2. spaCy NER           -> persons, groups/orgs, places.
  3. Regex               -> phone numbers, MGRS/lat-long grids.

Everything is normalized here so downstream matching compares like with like.
"""
from __future__ import annotations

import json
import pathlib
import re

from .models import Feature, Incident

# ---- regex helpers ---------------------------------------------------------
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3}[-.\s]?\d{3,4}\b")
_MGRS = re.compile(
    r"\b([1-9]|[1-5]\d|60)\s?[C-HJ-NP-X]\s?[A-HJ-NP-Z]{2}\s?\d{2,5}(?:\s?\d{2,5})?\b"
)
_LATLON = re.compile(r"[-+]?\b\d{1,2}\.\d{3,}\s*[,;\s]+[-+]?\d{1,3}\.\d{3,}\b")

# Size / calibre / dimensions, e.g. "107mm", "60 cm", "~1 m", "12 inch".
_SIZE = re.compile(r"\b(\d{1,3})\s?(mm|cm|m|in|inch|inches|ft)\b", re.IGNORECASE)
_QUAL_SIZE = re.compile(r"\b(small|medium|large|large-calibre|heavy|man-portable)\b", re.IGNORECASE)
# A photo/image reference embedded in a report, e.g. "photo: img_042.jpg".
_PHOTO_REF = re.compile(r"\b(?:photo|image|img|picture)\s*[:#-]?\s*([\w./-]+\.(?:jpg|jpeg|png|heic))\b",
                        re.IGNORECASE)

# Group/network names in reports are often "the X Cell/Network/Group/Faction".
_GROUP = re.compile(
    r"\b((?:the\s+)?[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)?\s+"
    r"(?:Cell|Network|Group|Faction|Brigade|Front|Movement))\b"
)


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


class FeatureExtractor:
    def __init__(self, taxonomy_path: str | pathlib.Path, use_ner: bool = True):
        raw = json.loads(pathlib.Path(taxonomy_path).read_text(encoding="utf-8"))
        # Build (compiled alias regex, facet, canonical) triples, longest alias
        # first so "command wire" wins over "wire".
        self.rules: list[tuple[re.Pattern, str, str]] = []
        for facet, values in raw.items():
            if facet.startswith("_"):
                continue
            for canonical, aliases in values.items():
                for alias in sorted(aliases, key=len, reverse=True):
                    pat = re.compile(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])",
                                     re.IGNORECASE)
                    self.rules.append((pat, facet, canonical))

        self.nlp = None
        if use_ner:
            import spacy
            self.nlp = spacy.load("en_core_web_sm", disable=["lemmatizer"])

    # -- feature (device/ttp) extraction via taxonomy ------------------------
    def _features(self, text: str) -> list[Feature]:
        seen: dict[tuple[str, str], Feature] = {}
        for pat, facet, canonical in self.rules:
            m = pat.search(text)
            if m and (facet, canonical) not in seen:
                seen[(facet, canonical)] = Feature(facet, canonical, surface=m.group(0))
        return list(seen.values())

    # -- entity extraction ---------------------------------------------------
    def _entities(self, text: str, inc: Incident) -> None:
        for m in _PHONE.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) >= 9:                    # avoid catching short numbers
                inc.phones.add(_norm_ws(m.group(0)))
        if not inc.grid:
            g = _MGRS.search(text) or _LATLON.search(text)
            if g:
                inc.grid = _norm_ws(g.group(0))
        for m in _GROUP.finditer(text):
            inc.groups.add(_norm_ws(m.group(1)))

        if self.nlp is not None:
            doc = self.nlp(text)
            for ent in doc.ents:
                if ent.label_ == "PERSON":
                    inc.persons.add(_norm_ws(ent.text))
                elif ent.label_ in ("GPE", "LOC", "FAC"):
                    inc.places.add(_norm_ws(ent.text))
                elif ent.label_ == "ORG":
                    # keep multi-word orgs; drop short all-caps acronym noise
                    t = ent.text.strip()
                    if not (t.isupper() and len(t) <= 4):
                        inc.groups.add(_norm_ws(t))

    def extract(self, inc: Incident) -> Incident:
        text = inc.narrative or ""
        inc.features = self._features(text)
        # Size / calibre as normalized features (e.g. size=107mm, size=small).
        for m in _SIZE.finditer(text):
            val = f"{m.group(1)}{m.group(2).lower().replace('inches','in').replace('inch','in')}"
            inc.features.append(Feature("size", val, surface=m.group(0)))
        for m in _QUAL_SIZE.finditer(text):
            inc.features.append(Feature("size", m.group(1).lower(), surface=m.group(0)))
        # De-dupe features by (facet,value).
        seen, uniq = set(), []
        for f in inc.features:
            if f.key() not in seen:
                seen.add(f.key()); uniq.append(f)
        inc.features = uniq
        # Photo reference (only recorded, never analyzed).
        if not inc.photo:
            pm = _PHOTO_REF.search(text)
            if pm:
                inc.photo = pm.group(1)
        self._entities(text, inc)
        # If no explicit primary location was provided, adopt the first place.
        if not inc.location and inc.places:
            inc.location = sorted(inc.places)[0]
        return inc

    def extract_all(self, incidents: list[Incident]) -> list[Incident]:
        return [self.extract(i) for i in incidents]
