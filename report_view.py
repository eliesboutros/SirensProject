"""Presentation helpers for the report page: plain-language labels, the
report text with each finding highlighted, and one ranked list of links.

Nothing here changes what Sirens extracts or how it scores; it only says it
in words an analyst reads at a glance, and shows where in the text each
finding came from.
"""
from __future__ import annotations

import re

from markupsafe import Markup, escape

import ui_icons

# Facet -> (plain label, group). Groups set the highlight colour.
FACETS = {
    "object_type": ("Object", "device"),
    "initiation": ("Initiation", "device"),
    "trigger": ("Trigger", "device"),
    "container": ("Container", "device"),
    "charge_label": ("Main charge", "device"),
    "size": ("Size", "device"),
    "colour": ("Colour", "device"),
    "shape": ("Shape", "device"),
    "emplacement": ("Placement", "place"),
    "ttp": ("Target", "target"),
}
GROUPS = [
    ("device", "The object"),
    ("place", "Where it was placed"),
    ("target", "Target"),
    ("people", "People, groups and phones"),
    ("places", "Places named"),
]
_VALUES = {
    "hme_label": "homemade explosive", "military_label": "military explosive",
    "victim_operated": "victim-operated", "command_initiated": "command-initiated",
    "remote_controlled": "remote-controlled", "time_delay": "time delay",
    "buried_roadside": "buried at the roadside", "plastic_jug": "plastic jerrycan",
    "unexploded_ordnance": "unexploded ordnance",
}


def value_label(facet: str, value: str) -> str:
    v = _VALUES.get(value)
    if v:
        return v
    if facet == "ttp" and value.startswith("target_"):
        value = value[len("target_"):]
    return value.replace("_", " ")


def feature_label(key: str) -> str:
    """'trigger=pressure_plate' -> 'Trigger: pressure plate'."""
    facet, _, value = key.partition("=")
    name = FACETS.get(facet, (facet.replace("_", " ").capitalize(), ""))[0]
    return f"{name}: {value_label(facet, value)}"


def reason_label(reason: str) -> str:
    """'shared signature: trigger=pressure_plate, ttp=target_convoy' ->
    'Shares: Trigger: pressure plate, Target: convoy'."""
    r = re.sub(r"\b([a-z_]+)=([a-z0-9_]+)", lambda m: feature_label(m.group(0)), reason)
    return r.replace("shared signature:", "Shares").replace("same/near location", "Same or nearby place")


def entity_label(key: str) -> str:
    """'person:Meiss' -> 'Same person: Meiss'."""
    kind, _, value = key.partition(":")
    return {"person": "Same person", "group": "Same group", "phone": "Same phone"}.get(kind, kind) + f": {value}"


def findings(inc) -> list[dict]:
    """Everything Sirens read, grouped: [{group, title, items: [{label, value, surface}]}]."""
    by_group: dict[str, list] = {g: [] for g, _t in GROUPS}
    for f in inc.features:
        name, group = FACETS.get(f.facet, (f.facet.replace("_", " ").capitalize(), "device"))
        by_group[group].append({"label": name, "value": value_label(f.facet, f.value),
                                "surface": f.surface})
    for kind, values in (("Person", inc.persons), ("Group", inc.groups), ("Phone", inc.phones)):
        for v in sorted(values):
            by_group["people"].append({"label": kind, "value": v, "surface": v})
    for v in sorted(inc.places):
        by_group["places"].append({"label": "Place", "value": v, "surface": v})
    return [{"group": g, "title": t, "items": by_group[g]} for g, t in GROUPS if by_group[g]]


def highlight(text: str, groups: list[dict]) -> Markup:
    """The text with each finding's words marked (longest match wins on overlap)."""
    spans = []
    for g in groups:
        for it in g["items"]:
            s = (it["surface"] or "").strip()
            if len(s) < 2:
                continue
            for m in re.finditer(re.escape(s), text, flags=re.IGNORECASE):
                spans.append((m.start(), m.end(), g["group"], f'{it["label"]}: {it["value"]}'))
    spans.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    out, pos = [], 0
    for start, end, group, title in spans:
        if start < pos:
            continue
        out.append(escape(text[pos:start]))
        out.append(Markup('<mark class="hl hl-{}" title="{}">{}</mark>').format(
            group, title, text[start:end]))
        pos = end
    out.append(escape(text[pos:]))
    return Markup("").join(out)


def shared_terms(inc, keys: set[str]) -> list[dict]:
    """A past report's own findings limited to the shared ones, for highlighting it."""
    items = [{"label": "", "value": "", "surface": f.surface}
             for f in inc.features if f"{f.facet}={f.value}" in keys]
    return [{"group": "shared", "title": "", "items": items}]


def merged_links(result) -> list[dict]:
    """One ranked list from the two kinds of match. Shared features and people
    rank first (that is the link score); similar wording is shown beside it."""
    rows: dict[str, dict] = {}
    for h, link, band in result.get("structured", []):
        rows[h.incident_id] = {
            "inc": h, "score": link.score, "band": band,
            "shares": [feature_label(k) for k in link.shared_features]
                      + [entity_label(k) for k in link.shared_entities],
            "near": [reason_label(r) for r in link.reasons if r.startswith("same/near location")],
            "keys": set(link.shared_features), "wording": None, "wording_band": None}
    for h, sim, band in result.get("semantic", []):
        r = rows.setdefault(h.incident_id, {
            "inc": h, "score": None, "band": None, "shares": [], "near": [], "keys": set(),
            "wording": None, "wording_band": None})
        r["wording"], r["wording_band"] = sim, band
    ordered = sorted(rows.values(), key=lambda r: (r["score"] is None, -(r["score"] or 0),
                                                  -(r["wording"] or 0)))
    for r in ordered:
        r["compare"] = highlight(r["inc"].narrative or "", shared_terms(r["inc"], r["keys"]))
    return ordered


def munition_cards(entries) -> list[dict]:
    """Reference entries for the object types found, with their family icon."""
    return [{**e, "family": ui_icons.family_of(e["object_type"]),
             "family_name": ui_icons.FAMILY_NAME[ui_icons.family_of(e["object_type"])]}
            for e in entries]


COLOURS = {   # swatch for each listed colour (app.py _ITEM_COLORS)
    "black": "#1d1f21", "grey": "#8d949a", "olive / green": "#5f6b3a", "tan / sand": "#c9b48a",
    "brown / rust": "#8b4a24", "blue": "#2f5f9e", "red": "#b23a32", "yellow": "#e2b93b",
    "camouflage": "repeating-linear-gradient(45deg,#5f6b3a 0 6px,#8b7a52 6px 12px,#3d4a2a 12px 18px)",
    "unpainted metal": "linear-gradient(135deg,#d7dbde,#9aa2a8 55%,#e4e7e9)",
}
