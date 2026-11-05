"""Sirens — web console.

A browser front-end over the same analysis pipeline the CLI uses. Paste or type a
report; Sirens extracts its signature, compares it against every incident in the
local database (by shared features AND by meaning), and — if an Anthropic key is
configured — has Claude write a plain-English linkage assessment. Anything you
save is remembered and becomes part of what the next report is checked against.

Run:
    python app.py
Then open http://127.0.0.1:5000 in your browser.
"""
from __future__ import annotations

import pathlib
import re
import webbrowser
import random
from threading import Timer

from flask import (Flask, redirect, render_template_string, request,
                   send_from_directory, url_for)

from linker.ingest import load_incidents
from linker.extract import FeatureExtractor
from linker.match import Matcher
from linker.cluster import Clusterer
from linker import store, semantic, ai, reference, report
from linker.models import Incident
from linker.grid_ref import from_mgrs, to_mgrs
from linker import regions
import report_page

ROOT = pathlib.Path(__file__).resolve().parent
TAXONOMY = ROOT / "data" / "taxonomy" / "cied_lexicon.json"
SAMPLES = ROOT / "data" / "sample_incidents"
PHOTOS_DIR = ROOT / "data" / "photos"
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

# Images we accept for filing. They are stored and shown for the analyst to
# eyeball against linked incidents — never machine-analysed (that stays out of
# scope). One image per incident, named after the incident id.
ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB cap per upload

from brief_bp import brief_bp
app.register_blueprint(brief_bp)
from vendor_bp import vendor_bp; app.register_blueprint(vendor_bp)
from demo_bp import demo_bp; app.register_blueprint(demo_bp)
from review_bp import review_bp; app.register_blueprint(review_bp)
from dashboard_bp import dashboard_bp; app.register_blueprint(dashboard_bp)
from network_bp import network_bp; app.register_blueprint(network_bp)
import ui_menu; ui_menu.register(app)
import map_bp; app.register_blueprint(map_bp.map_bp)
import forms_ui; forms_ui.register(app, lambda: sorted(set(_LOCATION_ALIASES) | set(_CAZA_NAMES)))

# Load the extractor once (spaCy start-up cost paid a single time).
_EXTRACTOR = FeatureExtractor(TAXONOMY, use_ner=True)


def _slug_city(location: str | None) -> str:
    """Turn a free-text location into a filename-safe place slug.

    'Route Copper, Al-Fakir District' -> 'route-copper' (primary place only).
    Empty/odd input falls back to 'site' so a file is always nameable.
    """
    if not location:
        return "site"
    primary = location.split(",")[0]                      # keep the main place
    slug = re.sub(r"[^a-z0-9]+", "-", primary.lower()).strip("-")
    return slug or "site"


def _next_index(slug: str) -> int:
    """Next free sequence number for a place, e.g. route-copper-03 -> 4."""
    hi = 0
    for p in PHOTOS_DIR.glob(f"{slug}-*"):
        m = re.fullmatch(rf"{re.escape(slug)}-(\d+)", p.stem)
        if m:
            hi = max(hi, int(m.group(1)))
    return hi + 1


def _save_photo(file_storage, location, previous_photo: str | None = None) -> str | None:
    """Persist an uploaded image under a human-readable, location-based name.

    The stored name records *where the object was found*, e.g. 'beirut-02.jpg'
    or 'route-copper-05.png' — never a meaningless upload name. Returns the
    stored filename, or None if nothing usable was uploaded. Any image already
    on record for this incident is removed first, so a record carries one image.
    """
    if not file_storage or not file_storage.filename:
        return None
    ext = pathlib.Path(file_storage.filename).suffix.lower()
    if ext not in ALLOWED_PHOTO_EXT:
        return None
    slug = _slug_city(location)
    stored = f"{slug}-{_next_index(slug):02d}{ext}"
    try:
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        file_storage.save(str(PHOTOS_DIR / stored))     # write the new image first
    except OSError:
        return None
    if previous_photo and previous_photo != stored:     # only then drop the old one
        try:
            (PHOTOS_DIR / previous_photo).unlink()
        except OSError:
            pass
    return stored


@app.route("/photos/<path:name>")
def photo(name):
    """Serve a filed incident image. send_from_directory blocks path traversal."""
    return send_from_directory(PHOTOS_DIR, name)


@app.template_global()
def photo_url(inc):
    """URL for an incident's filed image, or None if there is no real file.

    Old text-only references (e.g. sample data that names 'img_003.jpg' with no
    actual file) return None and simply render as no image — nothing breaks.
    """
    name = getattr(inc, "photo", None)
    if name and (PHOTOS_DIR / name).exists():
        return url_for("photo", name=name)
    return None


@app.template_global()
def ref_all():
    """Every reference entry, for the browse picker."""
    return reference.all_entries()


@app.template_global()
def ref_disclaimer():
    """Library-wide recognition/handling disclaimer, shown on every panel."""
    return reference.disclaimer()


def _score_band(x: float) -> str:
    return "strong" if x >= 0.66 else "medium" if x >= 0.40 else "weak"


def _analyse(new_inc: Incident, run_llm: bool):
    """Compare a freshly-extracted incident against the stored history."""
    history = store.all_incidents()
    history = [h for h in history if h.incident_id != new_inc.incident_id]

    # Structured (taxonomy) matches — fit corpus stats on history + the new one.
    structured = []
    matcher = Matcher().fit(history + [new_inc])
    for h in history:
        link = matcher.score(new_inc, h)
        if link.score > 0 and (link.shared_features or link.shared_entities):
            structured.append((h, link))
    structured.sort(key=lambda t: t[1].score, reverse=True)
    structured = structured[:6]

    # Meaning matches (offline).
    sem = semantic.SemanticIndex(history).top_matches(
        new_inc.narrative, k=6, exclude_id=new_inc.incident_id) if history else []

    # LLM assessment (optional).
    assessment = None
    if run_llm:
        assessment = ai.assess(new_inc, structured[:4], sem[:4])

    return {
        "structured": [(h, link, _score_band(link.score)) for h, link in structured],
        "semantic": [(h, s, _score_band(s)) for h, s in sem],
        "assessment": assessment,
    }


def _page(mode="form", form=None, result=None, error=None, photo_name=None):
    """Render the report page (report_page.py) with everything it needs."""
    return report_page.render(
        mode=mode, form=form or {}, result=result, error=error, status=_status(),
        suggested_id=store.next_incident_id(), photo_name=photo_name,
        have_map=map_bp.map_file().is_file(), photo_url=photo_url, **_form_options(form or {}))


@app.route("/report", methods=["GET"])
def index():
    return _page()


@app.route("/analyse", methods=["POST"])
def analyse():
    f = request.form
    narrative = (f.get("narrative") or "").strip()
    incident_id = (f.get("incident_id") or store.next_incident_id()).strip()

    # Validate the one thing Sirens actually needs *before* writing anything to
    # disk, so a rejected report never leaves a stray uploaded photo behind.
    if not narrative:
        return _page(form=f, error="Paste the report text first: it is what Sirens reads.",
                     photo_name=f.get("photo") or None)

    # Exact position (MGRS, a map pin, or legacy UTM) -> lat, lon + a display label.
    lat, lon, grid, grid_err = _resolve_grid(f)
    if grid_err:
        return _page(form=f, error=grid_err, photo_name=f.get("photo") or None)

    # Structured place: caza (dropdown, or from the pin) is authoritative for the
    # map; street is the exact where. A readable location string joins both.
    caza = (f.get("caza") or "").strip()
    if not caza and lat is not None:
        caza = regions.caza_at(lat, lon) or ""
    street = (f.get("street") or "").strip()
    location = ", ".join(p for p in (street, caza) if p) or (f.get("location") or None)

    existing = store.get_incident(incident_id)
    prev_photo = existing.photo if existing else None
    stored_photo = _save_photo(request.files.get("photo_file"), location,
                               previous_photo=prev_photo)
    if stored_photo is None:
        stored_photo = prev_photo or (f.get("photo") or None)

    inc = Incident(
        incident_id=incident_id,
        date=(f.get("date") or None),
        location=location,
        narrative=narrative,
        photo=stored_photo,
    )
    _EXTRACTOR.extract(inc)
    save = f.get("action") == "save"

    munition = (f.get("munition") or "").strip()
    item_color = ", ".join(p for p in ((f.get("item_color") or "").strip(),
                                        (f.get("item_color_other") or "").strip()) if p)
    conditions = f.getlist("condition")

    if save:
        store.add_incident(inc)
        _put_meta(incident_id, {
            "caza": caza or None,
            "street": street or None,
            "munition": munition or None,
            "color": item_color or None,
            "condition": conditions,
            "lat": lat, "lon": lon, "grid": grid,
        })

    result = _analyse(inc, run_llm=(f.get("use_ai") == "on"))
    result["incident"] = inc
    result["saved"] = save
    result["reference"] = reference.types_in(inc)
    result["meta"] = {
        "caza": caza, "street": street,
        "munition": munition, "munition_label": _MUNITION_LABEL.get(munition, ""),
        "color": item_color, "condition": conditions, "grid": grid,
        "grid_mgrs": to_mgrs(lat, lon) if lat is not None else "",
    }
    if save:
        return _page(mode="saved", result=result)
    # Analyse only: keep everything typed, including the caza found from the pin
    # and a photo already uploaded, so Save works without re-entering anything.
    form = f.to_dict()
    form["caza"] = caza
    form["condition"] = conditions
    return _page(form=form, result=result, photo_name=stored_photo)


@app.route("/seed", methods=["POST"])
def seed():
    incidents = load_incidents(SAMPLES)
    _EXTRACTOR.extract_all(incidents)
    store.add_incidents(incidents)
    return redirect(url_for("home.home_page"))


@app.route("/clear", methods=["POST"])
def clear():
    # Wipes every report: only when the person typed CLEAR on the Data page.
    if (request.form.get("confirm") or "").strip() != "CLEAR":
        return redirect(url_for("demo.demo_page", clear="refused"))
    store.clear()
    # The metadata sidecar and filed photos are app.py's own; keep them in step
    # with the database so a wipe doesn't leave orphaned records behind.
    try:
        META_FILE.unlink()
    except OSError:
        pass
    for p in PHOTOS_DIR.glob("*"):
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
    return redirect(url_for("home.home_page"))


def _status() -> dict:
    ai_ok, ai_reason = ai.available()
    return {
        "db_count": store.count(),
        "sem_mode": semantic.mode(),
        "sem_ok": semantic.has_vectors(),
        "ai_ok": ai_ok,
        "ai_reason": ai_reason,
    }


# The report page itself lives in report_page.py.


# ---------------------------------------------------------------------------
# Incident map — real choropleth of Lebanon's cazas (districts), shaded by
# incident count. Fully offline: the boundary geometry is bundled in
# data/regions.json (GADM v4.1 level 2) and projected + drawn as SVG right here.
# No map tiles, no geocoding, no API key, no CDN, no network. Reachable at /map.
#
# Interactive: wheel/drag to zoom + pan, hover for a caza tooltip, click a caza
# to zoom to it and pop up every report on record there (with its exact place
# text) right on the map. Sample incidents use invented place names;
# _LOCATION_ALIASES maps each onto a real caza. Typing a real caza in the
# Location field matches directly.
# ---------------------------------------------------------------------------
import json
import math

REGIONS_FILE = ROOT / "data" / "regions.json"

# --- Report attributes -----------------------------------------------------
# Each report is a marker on the map, coloured by *munition type*.
# (key, human label, marker colour).
_MUNITIONS = [
    ("ied",       "IED / roadside device", "#c0663f"),
    ("vbied",     "VBIED (vehicle-borne)",  "#7a3a3a"),
    ("uxo",       "UXO (unexploded ord.)",  "#c99a4a"),
    ("mine",      "Landmine / mine",        "#8770a0"),
    ("mortar",    "Mortar",                 "#5a80a3"),
    ("rocket",    "Rocket",                 "#4a9a8f"),
    ("missile",   "Missile / ATGM",         "#a3568f"),
    ("artillery", "Artillery shell",        "#8a7451"),
    ("grenade",   "Grenade / RPG",          "#6a9a6e"),
    ("cache",     "Weapons cache",          "#6b7c86"),
    ("other",     "Other / unknown",        "#9aa1a8"),
]
_MUNITION_COLOR = {k: c for k, _l, c in _MUNITIONS}
_MUNITION_LABEL = {k: l for k, l, _c in _MUNITIONS}

_CONDITIONS = ["buried", "surface-laid", "freshly emplaced", "aged / weathered",
               "damaged", "burned", "corroded", "intact"]
_ITEM_COLORS = ["black", "grey", "olive / green", "tan / sand", "brown / rust",
                "blue", "red", "yellow", "camouflage", "unpainted metal"]

# Keyword fallback so sample data (and any report filed without an explicit
# type) still gets a meaningful pin colour, read straight from its own text.
# Order matters: more specific patterns first. Overridden by an explicit type.
_MUNITION_HINTS = [
    ("vbied",     r"vbied|car\s?bomb|vehicle[- ]borne|truck bomb"),
    ("cache",     r"cache|weapons? (?:store|dump)|stockpile|arms dump"),
    ("mine",      r"landmine|minefield|\bmine\b"),
    ("mortar",    r"\bmortar"),
    ("rocket",    r"\brocket|107\s?mm|122\s?mm|\bgrad\b"),
    ("missile",   r"\bmissile|\batgm\b|kornet|guided munition"),
    ("artillery", r"artillery|\bshell\b|155\s?mm|130\s?mm|105\s?mm"),
    ("grenade",   r"grenade|\brpg\b"),
    ("uxo",       r"\buxo\b|unexploded|\bdud\b|\berw\b|abandoned ordnance"),
    ("ied",       r"\bied\b|improvised|roadside|pressure[- ]plate|command[- ]wire|"
                  r"victim[- ]operated|pipe bomb|\bdevice\b|\bvoied\b"),
]


def _infer_munition(inc, explicit):
    """Explicit type if filed; else guess from the narrative + extracted features."""
    if explicit:
        return explicit
    text = (getattr(inc, "narrative", "") or "").lower()
    feats = " ".join(
        f"{getattr(x, 'facet', '')} {getattr(x, 'value', '')}"
        for x in (getattr(inc, "features", None) or [])
    ).lower()
    hay = text + " " + feats
    for key, pat in _MUNITION_HINTS:
        if re.search(pat, hay):
            return key
    return "other"


# --- Per-report metadata sidecar -------------------------------------------
# app.py owns this file entirely; it never touches the linker store. It records
# the structured fields the form now captures (caza, street, type, colour,
# condition, precise lat/lon) keyed by incident id. The map reads it; missing
# entries simply fall back to the old alias behaviour, so nothing breaks.
META_FILE = ROOT / "data" / "report_meta.json"


def _load_meta():
    try:
        return json.loads(META_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_meta(meta):
    try:
        META_FILE.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    except OSError:
        pass


def _put_meta(incident_id, rec):
    """Store non-empty fields for an incident (or drop the record if all empty)."""
    rec = {k: v for k, v in rec.items() if v not in (None, "", [], {})}
    meta = _load_meta()
    if rec:
        meta[incident_id] = rec
    else:
        meta.pop(incident_id, None)
    _save_meta(meta)


# --- UTM <-> geographic (WGS84), pure math, no dependencies ----------------
# Lebanon straddles two UTM zones: 36N covers the coast and most of the country;
# 37N covers the eastern Beqaa / Baalbek-Hermel. Zone is stored per report and
# auto-detected from longitude for the live map read-out.
def _latlon_to_utm(lat, lon, force_zone=None):
    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    zone = force_zone or (int((lon + 180) // 6) + 1)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    latr = math.radians(lat)
    lonr = math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(latr) ** 2)
    T = math.tan(latr) ** 2
    C = ep2 * math.cos(latr) ** 2
    A = math.cos(latr) * (lonr - lon0)
    M = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * latr
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * latr)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * latr)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * latr))
    E = k0 * N * (A + (1 - T + C) * A ** 3 / 6
                  + (5 - 18 * T + T ** 2 + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000
    Nn = k0 * (M + N * math.tan(latr) * (A ** 2 / 2
               + (5 - T + 9 * C + 4 * C ** 2) * A ** 4 / 24
               + (61 - 58 * T + T ** 2 + 600 * C - 330 * ep2) * A ** 6 / 720))
    if lat < 0:
        Nn += 10000000
    return zone, E, Nn


def _utm_to_latlon(easting, northing, zone, north=True):
    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    x = easting - 500000
    y = northing if north else northing - 10000000
    M = y / k0
    mu = M / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    C1 = ep2 * math.cos(phi1) ** 2
    T1 = math.tan(phi1) ** 2
    N1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    R1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    D = x / (N1 * k0)
    lat = phi1 - (N1 * math.tan(phi1) / R1) * (
        D ** 2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 ** 2 - 9 * ep2) * D ** 4 / 24
        + (61 + 90 * T1 + 298 * C1 + 45 * T1 ** 2 - 252 * ep2 - 3 * C1 ** 2) * D ** 6 / 720)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    lon = lon0 + (D - (1 + 2 * T1 + C1) * D ** 3 / 6
                  + (5 - 2 * C1 + 28 * T1 - 3 * C1 ** 2 + 8 * ep2 + 24 * T1 ** 2)
                  * D ** 5 / 120) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)


def _fmt_grid(lat, lon):
    z, E, N = _latlon_to_utm(lat, lon)
    return f"{z}N {E:.0f}E {N:.0f}N"


def _parse_float(s):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _resolve_grid(f):
    """Turn whatever grid the form supplied (UTM or lat/lon) into lat, lon, a
    display label, and an optional error message. Out-of-range input is rejected
    with a note rather than silently producing a nonsense pin."""
    ref = (f.get("mgrs") or "").strip()
    if ref:
        try:
            lat, lon = from_mgrs(ref)
        except ValueError as e:
            return None, None, None, f"Grid reference not understood: {e}."
        return round(lat, 6), round(lon, 6), _fmt_grid(lat, lon), None
    mode = f.get("grid_mode") or "utm"
    lat = lon = None
    if mode == "latlon":
        raw_lat, raw_lon = f.get("lat"), f.get("lon")
        if not (raw_lat or raw_lon):
            return None, None, None, None
        lat, lon = _parse_float(raw_lat), _parse_float(raw_lon)
        if lat is None or lon is None:
            return None, None, None, "Enter both latitude and longitude as numbers."
    else:
        raw_e, raw_n = f.get("utm_e"), f.get("utm_n")
        if not (raw_e or raw_n):
            return None, None, None, None
        e, n = _parse_float(raw_e), _parse_float(raw_n)
        if e is None or n is None:
            return None, None, None, "Enter both UTM easting and northing as numbers."
        if not (100000 <= e <= 900000) or not (0 <= n <= 10000000):
            return None, None, None, ("UTM values look out of range — easting "
                                      "100000–900000, northing 0–10 000 000.")
        zone = 37 if (f.get("utm_zone") == "37") else 36
        lat, lon = _utm_to_latlon(e, n, zone, north=True)
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None, None, None, "Coordinates are outside valid Earth bounds."
    return round(lat, 6), round(lon, 6), _fmt_grid(lat, lon), None


def _form_options(f):
    """Option lists the New-report form needs, shared by every render path."""
    sel = f.getlist("condition") if hasattr(f, "getlist") else list(f.get("condition") or [])
    return dict(cazas=_CAZA_NAMES, munitions=_MUNITIONS,
                colors=_ITEM_COLORS, conditions=_CONDITIONS, sel_conditions=sel)


# Map the sample data's invented locations onto real Lebanese cazas so the
# choropleth has a spread to show. Delete/replace these as you enter real ones.
_LOCATION_ALIASES = {
    # Real South Lebanon towns -> their caza (exact GADM names from regions.json).
    # Bint Jbeil caza
    "Bint Jbeil":     "BintJbayl",
    "Aïn Ebel":       "BintJbayl",
    "Rmeish":         "BintJbayl",
    "Yaroun":         "BintJbayl",
    "Maroun al-Ras":  "BintJbayl",
    "Aitaroun":       "BintJbayl",
    "Chaqra":         "BintJbayl",
    "Tibnin":         "BintJbayl",
    "Ghandouriyeh":   "BintJbayl",
    # Marjaayoun caza
    "Marjayoun":      "Marjaayoun",
    "Khiam":          "Marjaayoun",
    "Kfar Kila":      "Marjaayoun",
    "Blida":          "Marjaayoun",
    "Meiss ej-Jabal": "Marjaayoun",
    "Deir Mimas":     "Marjaayoun",
    "Houla":          "Marjaayoun",
    # Nabatiyeh caza
    "Nabatieh":       "Nabatiyeh",
    "Kfar Tibnit":    "Nabatiyeh",
    "Zawtar":         "Nabatiyeh",
    "Kfar Roummane":  "Nabatiyeh",
    # Sour (Tyre) caza
    "Qana":           "Sour",
    "Tayr Harfa":     "Sour",
    "Naqoura":        "Sour",
    "Srifa":          "Sour",
    # Legacy invented sample-incident names (kept so the 13 demo samples still map).
    "Route Copper":      "Tripoli",
    "Al-Fakir District": "Akkar",
    "Green Village":     "Zahleh",
    "Hazar Junction":    "Baabda",
    "Central Market":    "Beirut",
    "Ministry Road":     "Saida",
    "North Gate":        "Zgharta",
    "Sector 7 bypass":   "Sour",
}


def _norm(s):
    """Loose key for matching place names regardless of case/spacing/punctuation."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _load_regions():
    """Load the bundled boundary geometry once, or None if the file is absent
    or malformed (a corrupt file must not crash the whole app at startup)."""
    try:
        return json.loads(REGIONS_FILE.read_text())
    except (OSError, ValueError):
        return None


_REGIONS = _load_regions()


_CAZA_NAMES = sorted({f["properties"]["name"] for f in _REGIONS["features"]}) if _REGIONS else []


def _district(location):
    """Real caza for a free-text location: first comma-part -> alias -> caza."""
    if not location or not location.strip():
        return None
    primary = location.split(",")[0].strip()
    return _LOCATION_ALIASES.get(primary, primary)


@app.route("/tree")
def link_tree():
    """Interactive force-directed link graph: which incidents connect to
    which, coloured by cluster. Runs the same matcher used by /analyse over
    every incident currently in the database, entirely offline."""
    incidents = store.all_incidents()
    if not incidents:
        return render_template_string(
            "<p style='font-family:monospace;padding:40px'>No incidents in the "
            "database yet. <a href='/'>Go back</a> and load or save some first.</p>")

    matcher = Matcher().fit(incidents)
    links = matcher.all_pairs(incidents, threshold=0.25)
    clusterer = Clusterer(incidents, links)
    clusters = clusterer.clusters(singletons=False)
    payload = clusterer.graph_payload()

    html_page = report.html_report(
        incidents, links, clusters, payload,
        title="Sirens — Incident Link Tree", nav=ui_menu.menu("tree"),
    )
    return html_page


def map_markers(incidents):
    """Markers for the map (web page and mobile app): an exact point when a
    grid was filed, otherwise the caza centre, spread so markers placed at the
    same caza do not overlap. Returns (markers, legend, unplaced count)."""
    canon = {_norm(n): n for n in _CAZA_NAMES}
    centres = map_bp.caza_centres()
    meta = _load_meta()
    markers, typecounts, percaza, unplaced = [], {}, {}, 0
    for inc in incidents:
        iid = inc.incident_id
        m = meta.get(iid, {})
        d = m.get("caza") or _district(inc.location)
        key = canon.get(_norm(d)) if d else None
        lat, lon = m.get("lat"), m.get("lon")
        exact = lat is not None and lon is not None
        if exact:
            mgrs_ref = to_mgrs(lat, lon)
        else:
            if key not in centres:
                unplaced += 1
                continue
            idx = percaza.get(key, 0)
            percaza[key] = idx + 1
            # the reference names the caza centre, not the display-spread marker
            mgrs_ref = to_mgrs(centres[key][1], centres[key][0])
            lon, lat = map_bp.spread(*centres[key], idx)
        mun = _infer_munition(inc, m.get("munition"))
        typecounts[mun] = typecounts.get(mun, 0) + 1
        snip = (inc.narrative or "").strip().replace("\n", " ")
        markers.append({
            "id": iid, "lon": round(lon, 6), "lat": round(lat, 6), "exact": exact,
            "caza": key or "", "date": inc.date or "", "loc": inc.location or "",
            "street": m.get("street", "") or "", "type": mun,
            "typelabel": _MUNITION_LABEL.get(mun, mun), "fill": _MUNITION_COLOR.get(mun, "#8a929a"),
            "item_color": m.get("color", "") or "", "condition": m.get("condition", []) or [],
            "grid": m.get("grid") or (_fmt_grid(lat, lon) if exact else ""), "mgrs": mgrs_ref,
            "snip": snip[:160] + ("…" if len(snip) > 160 else ""),
        })
    legend = [{"key": k, "label": l, "color": c, "count": typecounts[k]}
              for k, l, c in _MUNITIONS if typecounts.get(k)]
    return markers, legend, unplaced


@app.route("/map")
def incident_map():
    """Offline street map (map_bp.py); this only gathers the incident markers."""
    markers, legend, unplaced = map_markers(store.all_incidents())
    return map_bp.render_page(markers, legend, unplaced=unplaced)


def _regions_of(incidents):
    """{incident id: caza (canonical name) or None}, as the map places them."""
    meta = _load_meta()
    canon = {_norm(n): n for n in _CAZA_NAMES}
    out = {}
    for inc in incidents:
        d = meta.get(inc.incident_id, {}).get("caza") or _district(inc.location)
        out[inc.incident_id] = canon.get(_norm(d)) if d else None
    return out


# Mobile app interface (/api/v1): accounts, roles, regions. See api_bp.py.
import api_bp
api_bp.register(app, regions_of=_regions_of, extractor=_EXTRACTOR, put_meta=_put_meta,
                fmt_grid=_fmt_grid, munitions=_MUNITIONS, map_markers=map_markers)


def _marker_of(inc):
    """(type label, marker colour) for an incident, as on the map."""
    mun = _infer_munition(inc, _load_meta().get(inc.incident_id, {}).get("munition"))
    return _MUNITION_LABEL.get(mun, mun), _MUNITION_COLOR.get(mun, "#8a929a")


import home_bp
home_bp.register(app, status=_status, marker_of=_marker_of)
from munitions_bp import munitions_bp
app.register_blueprint(munitions_bp)


def _open():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    store.connect()  # ensure the DB file exists on first run
    Timer(1.2, _open).start()
    app.run(host="127.0.0.1", port=5000, debug=False)