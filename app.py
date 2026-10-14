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
from linker.grid_ref import to_mgrs

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


@app.route("/", methods=["GET"])
def index():
    return render_template_string(
        TEMPLATE,
        result=None, form={}, status=_status(),
        suggested_id=store.next_incident_id(),
        **_form_options({}),
    )


@app.route("/analyse", methods=["POST"])
def analyse():
    f = request.form
    narrative = (f.get("narrative") or "").strip()
    incident_id = (f.get("incident_id") or store.next_incident_id()).strip()
    opts = _form_options(f)

    # Validate the one thing Sirens actually needs *before* writing anything to
    # disk, so a rejected report never leaves a stray uploaded photo behind.
    if not narrative:
        return render_template_string(
            TEMPLATE, result=None, form=f, status=_status(),
            suggested_id=incident_id,
            error="Paste a report narrative first — that's what Sirens reads.",
            **opts)

    # Structured place: caza (dropdown) is authoritative for the map; street is
    # the exact where. A human-readable location string is composed from both,
    # falling back to any legacy free-text location field.
    caza = (f.get("caza") or "").strip()
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

    # Optional precise grid (UTM or lat/lon) -> lat, lon + a display label.
    lat, lon, grid, grid_err = _resolve_grid(f)
    munition = (f.get("munition") or "").strip()
    item_color = (f.get("item_color") or "").strip()
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
    }
    return render_template_string(
        TEMPLATE, result=result, form={}, status=_status(),
        suggested_id=store.next_incident_id(), error=grid_err,
        **_form_options({}))


@app.route("/seed", methods=["POST"])
def seed():
    incidents = load_incidents(SAMPLES)
    _EXTRACTOR.extract_all(incidents)
    store.add_incidents(incidents)
    return redirect(url_for("index"))


@app.route("/clear", methods=["POST"])
def clear():
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
    return redirect(url_for("index"))


def _status() -> dict:
    ai_ok, ai_reason = ai.available()
    return {
        "db_count": store.count(),
        "sem_mode": semantic.mode(),
        "sem_ok": semantic.has_vectors(),
        "ai_ok": ai_ok,
        "ai_reason": ai_reason,
    }


TEMPLATE = r"""{% import "forms_ui.html" as f %}{% macro ref_card(e) %}
<div class="refcard">
  <div class="reftitle">{{ e.label }} <span class="refkey mono">{{ e.object_type }}</span></div>
  {% if e.summary %}<p class="refsum">{{ e.summary }}</p>{% endif %}
  {% if e.specs %}
    <table class="refspecs">{% for row in e.specs %}<tr><th>{{ row[0] }}</th><td>{{ row[1] }}</td></tr>{% endfor %}</table>
  {% endif %}
  {% if e.ammunition %}
    <div class="reflab">Ammunition categories</div>
    <ul class="reflist">{% for a in e.ammunition %}<li>{{ a }}</li>{% endfor %}</ul>
  {% endif %}
  {% if e.deployment %}
    <div class="reflab">Employment</div>
    <ul class="reflist">{% for d in e.deployment %}<li>{{ d }}</li>{% endfor %}</ul>
  {% endif %}
  {% if e.responder_note %}<div class="refnote"><strong>Responder note.</strong> {{ e.responder_note }}</div>{% endif %}
  {% if e.sources %}<div class="refsrc">{{ e.sources|join('; ') }}</div>{% endif %}
</div>
{% endmacro %}
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens — Incident Link Console</title>
<style>
  :root{
    --ink:#16202b; --ink-soft:#3a4652; --line:#e2e6e3; --line-2:#eef0ee;
    --surface:#f4f6f3; --panel:#ffffff; --sig:#b5761f; --sig-soft:#f3e7d3;
    --strong:#1f7a4d; --strong-bg:#e7f2ec; --medium:#8a6a13; --medium-bg:#f6efdc;
    --weak:#7a8791; --weak-bg:#eef1f0; --link:#2d5b8e;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Roboto Mono",monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--surface);color:var(--ink);font-family:var(--sans);
       line-height:1.5;-webkit-font-smoothing:antialiased;position:relative}
  body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
       background:url('/static/siren-mark.jpeg') no-repeat center center;
       background-size:min(70vw,1100px);opacity:.06;filter:grayscale(1)}
  .bar,.wrap{position:relative;z-index:1}
  a{color:var(--link)}
  .bar{display:flex;align-items:center;gap:20px;flex-wrap:wrap;
       padding:18px 32px;background:var(--ink);color:#eef2f5;
       border-bottom:3px solid var(--sig)}
  .brand{font-family:var(--mono);font-weight:600;letter-spacing:.16em;
         text-transform:uppercase;font-size:15px}
  .brand small{display:block;letter-spacing:.06em;font-size:10px;color:#9fb0bd;
               font-weight:400;margin-top:2px}
  .badges{margin-left:auto;display:flex;gap:10px;flex-wrap:wrap}
  .badge{font-family:var(--mono);font-size:11px;letter-spacing:.04em;
         padding:5px 10px;border-radius:2px;background:#22303d;color:#cdd8e0;
         border:1px solid #2c3c4a;white-space:nowrap}
  .badge .dot{display:inline-block;width:7px;height:7px;border-radius:50%;
              margin-right:6px;vertical-align:middle;background:var(--weak)}
  .badge.on .dot{background:#54d08a}.badge.off .dot{background:#d0574f}
  .wrap{max-width:1720px;margin:0 auto;padding:40px 48px 90px}
  .grid{display:grid;grid-template-columns:minmax(0,560px) minmax(0,1fr);gap:40px;align-items:start}
  @media(max-width:1100px){.wrap{padding:28px 20px 60px}.grid{grid-template-columns:1fr}}
  @media(max-width:840px){.grid{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:9px;
        box-shadow:0 1px 2px rgba(22,32,43,.04),0 4px 16px rgba(22,32,43,.05)}
  .card h2{margin:0;padding:14px 18px;border-bottom:1px solid var(--line-2);
           font-size:12px;letter-spacing:.14em;text-transform:uppercase;
           color:var(--ink-soft);font-family:var(--mono);font-weight:600}
  .card .body{padding:24px 26px}
  label{display:block;font-size:12px;letter-spacing:.03em;color:var(--ink-soft);
        margin:0 0 5px;font-weight:600}
  input[type=text],textarea{width:100%;padding:9px 11px;border:1px solid var(--line);
        border-radius:4px;font-family:var(--sans);font-size:14px;color:var(--ink);
        background:#fcfdfc}
  input[type=text]:focus,textarea:focus{outline:2px solid var(--link);
        outline-offset:1px;border-color:var(--link)}
  textarea{min-height:230px;resize:vertical;line-height:1.6}
  .row{display:flex;gap:12px}.row>div{flex:1;min-width:0}
  .field{margin-bottom:20px}
  .mono{font-family:var(--mono)}
  .hint{font-size:12px;color:var(--weak);margin-top:5px}
  .checks{display:flex;flex-wrap:wrap;gap:12px 22px;margin-top:4px}
  .chk{display:inline-flex;align-items:center;gap:8px;margin:0;font-weight:500;
       font-size:14px;color:var(--ink-soft);cursor:pointer;padding:4px 0}
  .chk input{width:17px;height:17px;margin:0}
  .gridmode{display:flex;gap:18px;margin-bottom:4px}
  .gridrow{margin-top:8px}
  .mini{font-size:11px;letter-spacing:.02em;color:var(--weak);margin:0 0 4px;font-weight:600}
  input[type=file]{width:100%;font-size:13px;color:var(--ink-soft)}
  input[type=file]::file-selector-button{font-family:var(--sans);font-size:13px;
        font-weight:600;padding:8px 13px;margin-right:11px;border:1px solid var(--ink);
        border-radius:4px;background:#fff;color:var(--ink);cursor:pointer}
  input[type=file]::file-selector-button:hover{background:var(--line-2)}
  .shot{display:block;margin-top:6px;width:max-content;max-width:100%}
  .shot img{max-width:100%;max-height:300px;border:1px solid var(--line);
        border-radius:5px;display:block}
  .thumb{display:inline-block;margin-top:9px;line-height:0}
  .thumb img{width:78px;height:78px;object-fit:cover;border:1px solid var(--line);
        border-radius:4px;display:block}
  /* munitions reference */
  select{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:4px;
        font-family:var(--sans);font-size:14px;color:var(--ink);background:#fcfdfc}
  select:focus{outline:2px solid var(--link);outline-offset:1px;border-color:var(--link)}
  .refcard{border:1px solid var(--line);border-left:4px solid var(--sig);border-radius:5px;
        padding:13px 15px;margin-bottom:12px;background:#fffdf9}
  .reftitle{font-weight:700;font-size:15px;color:var(--ink);display:flex;
        align-items:center;gap:9px;flex-wrap:wrap}
  .refkey{font-size:11px;font-weight:600;color:#7a4e12;background:var(--sig-soft);
        border:1px solid #e6d3b0;border-radius:3px;padding:2px 7px}
  .refsum{font-size:13.5px;color:var(--ink-soft);margin:8px 0 10px;line-height:1.55}
  .refspecs{width:100%;border-collapse:collapse;font-size:13px;margin:0 0 10px}
  .refspecs th{text-align:left;font-weight:600;color:var(--ink-soft);white-space:nowrap;
        padding:3px 12px 3px 0;vertical-align:top;width:38%}
  .refspecs td{padding:3px 0;color:var(--ink)}
  .reflab{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--weak);
        font-family:var(--mono);margin:6px 0 5px}
  .reflist{margin:0 0 10px;padding-left:18px;font-size:13px;color:var(--ink-soft)}
  .reflist li{padding:1px 0}
  .refnote{font-size:13px;color:#8a3b12;background:#fbf0e6;border:1px solid #eecdb0;
        border-radius:4px;padding:9px 12px;margin:4px 0 8px}
  .refsrc{font-size:11.5px;color:var(--weak)}
  .actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:6px}
  .btn{font-family:var(--sans);font-size:14px;font-weight:600;padding:10px 16px;
       border-radius:4px;border:1px solid var(--ink);background:var(--ink);
       color:#fff;cursor:pointer}
  .btn:hover{background:#22303d}
  .btn.ghost{background:#fff;color:var(--ink)}
  .btn.ghost:hover{background:var(--line-2)}
  .toggle{display:flex;align-items:center;gap:7px;font-size:13px;color:var(--ink-soft);
          margin-left:auto;font-weight:500}
  .toggle input{width:16px;height:16px}
  .toggle.disabled{opacity:.5}
  .err{background:#fbeceb;border:1px solid #e7b7b2;color:#a4332b;padding:10px 14px;
       border-radius:4px;font-size:13px;margin-bottom:14px}
  .note{font-size:12.5px;color:var(--ink-soft);background:var(--line-2);
        border-radius:4px;padding:9px 12px;margin-bottom:14px}
  .empty{color:var(--weak);font-size:14px;padding:8px 2px}
  /* extracted signature chips */
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
  .chip{font-family:var(--mono);font-size:11.5px;padding:3px 8px;border-radius:3px;
        background:var(--sig-soft);color:#7a4e12;border:1px solid #e6d3b0}
  .chip.ent{background:#e9eef4;color:#274a6e;border-color:#cdd9e6}
  .subhead{font-size:11px;letter-spacing:.12em;text-transform:uppercase;
           color:var(--weak);font-family:var(--mono);margin:16px 0 8px}
  .subhead:first-child{margin-top:0}
  /* match cards — the signature element */
  .match{border:1px solid var(--line);border-left:4px solid var(--weak);
         border-radius:5px;padding:12px 14px;margin-bottom:10px;background:#fff}
  .match.strong{border-left-color:var(--strong)}
  .match.medium{border-left-color:var(--medium)}
  .match .top{display:flex;align-items:center;gap:10px}
  .score{font-family:var(--mono);font-weight:700;font-size:13px;padding:3px 8px;
         border-radius:3px;min-width:52px;text-align:center;color:var(--weak);
         background:var(--weak-bg)}
  .score.strong{color:var(--strong);background:var(--strong-bg)}
  .score.medium{color:var(--medium);background:var(--medium-bg)}
  .mid{font-family:var(--mono);font-weight:600;font-size:13px}
  .loc{color:var(--weak);font-size:12.5px;margin-left:auto;text-align:right}
  .reasons{margin:8px 0 0;padding-left:2px;list-style:none;font-size:13px;color:var(--ink-soft)}
  .reasons li{padding:2px 0 2px 16px;position:relative}
  .reasons li:before{content:"";position:absolute;left:2px;top:10px;width:6px;height:6px;
        background:var(--sig);border-radius:50%}
  .snippet{font-size:13px;color:var(--ink-soft);margin-top:6px}
  /* AI panel */
  .ai{border:1px solid #cdd9e6;background:#f5f9fd;border-radius:6px;padding:0;margin-top:4px}
  .ai h3{margin:0;padding:11px 16px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;
         font-family:var(--mono);color:#274a6e;border-bottom:1px solid #dce6f0;
         display:flex;align-items:center;gap:8px}
  .ai .txt{padding:14px 16px;font-size:14px;line-height:1.6;white-space:pre-wrap}
  .ai .off{padding:12px 16px;font-size:13px;color:var(--ink-soft)}
  .tag{font-family:var(--mono);font-size:10px;background:#274a6e;color:#fff;
       padding:2px 7px;border-radius:2px;margin-left:auto;letter-spacing:.05em}
  footer{max-width:1180px;margin:0 auto;padding:0 22px 40px;color:var(--weak);
         font-size:12px}
  @media(prefers-reduced-motion:no-preference){
    .result-card{animation:rise .28s ease both}
    @keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  }
</style>
{{ f.assets() }}
</head>
<body>
<div class="bar">
  <div class="brand">Sirens<small>C-IED Incident Link Console</small></div>
  {{ sirens_menu('console') }}
  <div class="badges">
    <span class="badge {{ 'on' if status.db_count else 'off' }}"><span class="dot"></span>{{ status.db_count }} in database</span>
    <span class="badge {{ 'on' if status.sem_ok else 'off' }}"><span class="dot"></span>meaning: {{ 'vectors' if status.sem_ok else 'lexical' }}</span>
    <span class="badge {{ 'on' if status.ai_ok else 'off' }}"><span class="dot"></span>AI: {{ 'ready' if status.ai_ok else 'off' }}</span>
  </div>
</div>

<div class="wrap">
<div class="grid">

  <!-- LEFT: input -->
  <section class="card">
    <h2>New report</h2>
    <div class="body">
      {% if result and result.saved %}<div class="f-saved" role="status">Saved <strong class="mono">{{ result.incident.incident_id }}</strong> to the database. Its likely network is shown on the right.</div>{% endif %}
      <form class="f-form" method="post" action="/analyse" enctype="multipart/form-data" novalidate>
        {{ f.form_error(error) }}
        {% call f.section("When & where") %}
          {{ f.input("incident_id", "Incident ID", "incident_id", value=(form.incident_id or suggested_id), mono=True) }}
          {{ f.input("date", "Date", "date", value=form.date, placeholder="2026-03-04", rules="date-advisory", optional=True) }}
          {{ f.select("caza", "Caza (district)", "caza", cazas, selected=form.caza, blank="— select caza —", optional=True) }}
          {{ f.input("street", "Town, village or street", "street", value=form.street, placeholder="e.g. Yaroun, main road",
                     list="placelist", rules="place:placelist:caza", optional=True) }}
          <datalist id="placelist">{% for pl in map_places() %}<option value="{{ pl }}">{% endfor %}</datalist>
        {% endcall %}
        {% call f.section("What happened") %}
          {{ f.textarea("narrative", "Report narrative", "narrative", value=form.narrative, rules="required",
                        placeholder="Paste the incident report here. Free text is fine: messy field reporting is what Sirens is built for.",
                        required_msg="Paste the report narrative: it is the one field Sirens needs.") }}
          {{ f.select("munition", "Munition / device type", "munition", munitions, selected=form.munition, blank="— select type —", optional=True) }}
        {% endcall %}
        {% set more_open = form.item_color or sel_conditions or form.utm_e or form.utm_n or form.lat or form.lon %}
        {% call f.more("More details", open=more_open, sub="colour, condition, grid reference, photo") %}
          {{ f.input("item_color", "Item colour / markings", "item_color", value=form.item_color, list="colorlist", placeholder="olive, rust, unpainted…", optional=True) }}
          <datalist id="colorlist">{% for c in colors %}<option value="{{ c }}">{% endfor %}</datalist>
          {{ f.choices("condition", "Condition", "condition", conditions, checked=sel_conditions, optional=True) }}
          {{ f.choices("grid_mode", "Grid reference", "grid_mode", [("utm", "UTM"), ("latlon", "Lat / Lon")], checked=[form.grid_mode or 'utm'], kind="radio", optional=True) }}
          <div class="f-wide f-gridrow" id="utmrow">
            {{ f.select("utm_zone", "Zone", "utm_zone", [("36", "36"), ("37", "37")], selected=(form.utm_zone or "36")) }}
            {{ f.input("utm_e", "Easting", "utm_e", value=form.utm_e, placeholder="731351", mono=True, inputmode="decimal", rules="number range:100000,900000 pair:utm_n") }}
            {{ f.input("utm_n", "Northing", "utm_n", value=form.utm_n, placeholder="3753199", mono=True, inputmode="decimal", rules="number range:0,10000000 pair:utm_e") }}
          </div>
          <div class="f-wide f-gridrow" id="llrow" style="display:none">
            {{ f.input("lat", "Latitude", "lat", value=form.lat, placeholder="33.2700", mono=True, inputmode="decimal", rules="number range:-90,90 pair:lon") }}
            {{ f.input("lon", "Longitude", "lon", value=form.lon, placeholder="35.2000", mono=True, inputmode="decimal", rules="number range:-180,180 pair:lat") }}
          </div>
          <div class="f-wide">
            <div class="f-field">
              {{ f.label("photo_file", "Photo", "photo_file", optional=True) }}
              <input class="f-input" type="file" id="photo_file" name="photo_file" accept="image/*" aria-describedby="e-photo_file">
              <div class="f-error" id="e-photo_file" aria-live="polite"></div>
            </div>
          </div>
        {% endcall %}
        <div class="f-actions">
          <button class="f-btn" type="submit" name="action" value="analyse" data-busy-text="Analysing…">Analyse</button>
          <button class="f-btn ghost" type="submit" name="action" value="save" data-busy-text="Saving…">Save to database</button>
          {{ f.toggle("use_ai", "AI assessment", "use_ai", checked=status.ai_ok, disabled=not status.ai_ok,
                      note=('' if status.ai_ok else 'Off: ' ~ status.ai_reason)) }}
        </div>
      </form>
    </div>
  </section>

  <!-- RIGHT: results -->
  <section>
  {% if not result %}
    <div class="card"><div class="body">
      {% if status.db_count == 0 %}
        <p class="empty">The database is empty. Load the 40 fabricated sample incidents to try it, then paste a new report to see what it links to.</p>
        <form method="post" action="/seed"><button class="btn" type="submit">Load demo data (fabricated)</button></form>
      {% else %}
        <p class="empty">Paste a report on the left and press <strong>Analyse</strong>. Sirens checks it against the {{ status.db_count }} incidents on record — by shared signature and by meaning — and, with AI on, explains the strongest links.</p>
        <div class="subhead">Or explore the record</div>
        <div class="matches">
          <a class="match" href="/dashboard" style="display:block;text-decoration:none;color:inherit"><span class="mid">Dashboard</span> <span class="loc">statistics, networks and data quality</span></a>
          <a class="match" href="/review" style="display:block;text-decoration:none;color:inherit"><span class="mid">Review links</span> <span class="loc">confirm, reject or flag each link</span></a>
          <a class="match" href="/tree" style="display:block;text-decoration:none;color:inherit"><span class="mid">Link tree</span> <span class="loc">graph of linked incidents</span></a>
        </div>
        <form method="post" action="/clear" onsubmit="return confirm('Delete all stored incidents?')">
          <button class="btn ghost" type="submit">Clear database</button></form>
      {% endif %}
    </div></div>
  {% else %}
    <div class="card result-card">
      <h2>Signature extracted &mdash; <span class="mono">{{ result.incident.incident_id }}</span>{% if result.saved %} &nbsp;·&nbsp; saved{% endif %}</h2>
      <div class="body">
        {% set inc = result.incident %}
        <div class="subhead">Device / TTP features</div>
        {% if inc.features %}
          <div class="chips">{% for f in inc.features %}<span class="chip">{{ f.facet }}={{ f.value }}</span>{% endfor %}</div>
        {% else %}<div class="empty">No taxonomy features matched this text.</div>{% endif %}

        {% if inc.persons or inc.groups or inc.phones %}
          <div class="subhead">Entities</div>
          <div class="chips">
            {% for p in inc.persons %}<span class="chip ent">person: {{ p }}</span>{% endfor %}
            {% for g in inc.groups %}<span class="chip ent">group: {{ g }}</span>{% endfor %}
            {% for ph in inc.phones %}<span class="chip ent">phone: {{ ph }}</span>{% endfor %}
          </div>
        {% endif %}

        {% set m = result.meta %}
        {% if m and (m.caza or m.street or m.munition_label or m.color or m.condition or m.grid) %}
          <div class="subhead">Filed details{% if not result.saved %} <span style="color:var(--weak);text-transform:none;letter-spacing:0">(save to keep them with the record)</span>{% endif %}</div>
          <div class="chips">
            {% if m.caza %}<span class="chip ent">caza: {{ m.caza }}</span>{% endif %}
            {% if m.street %}<span class="chip ent">place: {{ m.street }}</span>{% endif %}
            {% if m.munition_label %}<span class="chip">type: {{ m.munition_label }}</span>{% endif %}
            {% if m.color %}<span class="chip">colour: {{ m.color }}</span>{% endif %}
            {% for cnd in m.condition %}<span class="chip">{{ cnd }}</span>{% endfor %}
            {% if m.grid %}<span class="chip mono">{{ m.grid }}</span>{% endif %}
          </div>
        {% endif %}

        {% set purl = photo_url(inc) %}
        {% if purl %}
          <div class="subhead">Photo on file{% if not result.saved %} <span style="color:var(--weak);text-transform:none;letter-spacing:0">(save to keep it with the record)</span>{% endif %}</div>
          <a class="shot" href="{{ purl }}" target="_blank" rel="noopener">
            <img src="{{ purl }}" alt="Filed photo for {{ inc.incident_id }}"></a>
          <div class="hint mono">{{ inc.photo }}</div>
        {% endif %}
      </div>
    </div>
    {% if result.saved %}<div class="card result-card" style="margin-top:16px" hx-get="{{ url_for('network.panel', incident_id=result.incident.incident_id) }}" hx-trigger="load"><h2>Likely network</h2><div class="body"><div class="empty">Finding the network this report falls into&hellip; (if this stays, see <a href="/review">review links</a>)</div></div></div>{% endif %}

    {% if result.reference %}
      <div class="card result-card" style="margin-top:16px">
        <h2>Type reference &mdash; recognised in this report</h2>
        <div class="body">
          <div class="note">{{ ref_disclaimer() }}</div>
          {% for e in result.reference %}{{ ref_card(e) }}{% endfor %}
        </div>
      </div>
    {% endif %}

    {% if result.assessment %}
      <div class="ai result-card">
        <h3>AI linkage assessment
          {% if result.assessment.ok %}<span class="tag">{{ result.assessment.model }}</span>{% endif %}</h3>
        {% if result.assessment.ok %}
          <div class="txt">{{ result.assessment.text }}</div>
          <div class="off" style="border-top:1px solid #dce6f0;padding-top:9px;margin-top:2px">
            Generated by a small local model ({{ result.assessment.model }}) — verify every
            claim against the <strong>Links found</strong> panel below before acting on it.
          </div>
        {% else %}
          <div class="off">Assessment unavailable — {{ result.assessment.reason }}</div>
        {% endif %}
      </div>
    {% endif %}

    <div class="card result-card" style="margin-top:16px">
      <h2>Links found</h2>
      <div class="body">
        <div class="subhead">By shared signature</div>
        {% if result.structured %}
          {% for h, link, band in result.structured %}
          <div class="match {{ band }}">
            <div class="top">
              <span class="score {{ band }}">{{ '%.2f'|format(link.score) }}</span>
              <span class="mid">{{ h.incident_id }}</span>
              <span class="loc">{{ h.location or '—' }}{% if h.date %} · {{ h.date }}{% endif %}</span>
            </div>
            {% if link.reasons %}<ul class="reasons">{% for r in link.reasons %}<li>{{ r }}</li>{% endfor %}</ul>{% endif %}
            {% set hp = photo_url(h) %}
            {% if hp %}<a class="thumb" href="{{ hp }}" target="_blank" rel="noopener"><img src="{{ hp }}" alt="Photo on file for {{ h.incident_id }}"></a>{% endif %}
          </div>
          {% endfor %}
        {% else %}<div class="empty">No shared-signature links above threshold.</div>{% endif %}

        <div class="subhead">By meaning ({{ 'word vectors' if status.sem_ok else 'text overlap' }})</div>
        {% if result.semantic %}
          {% for h, sim, band in result.semantic %}
          <div class="match {{ band }}">
            <div class="top">
              <span class="score {{ band }}">{{ '%.2f'|format(sim) }}</span>
              <span class="mid">{{ h.incident_id }}</span>
              <span class="loc">{{ h.location or '—' }}</span>
            </div>
            <div class="snippet">{{ h.narrative[:160] }}{% if h.narrative|length > 160 %}…{% endif %}</div>
            {% set hp = photo_url(h) %}
            {% if hp %}<a class="thumb" href="{{ hp }}" target="_blank" rel="noopener"><img src="{{ hp }}" alt="Photo on file for {{ h.incident_id }}"></a>{% endif %}
          </div>
          {% endfor %}
        {% else %}<div class="empty">Nothing to compare against yet — save a few incidents first.</div>{% endif %}
      </div>
    </div>
  {% endif %}
  </section>
</div>

<section class="card" style="margin-top:22px">
  <h2>Munitions reference</h2>
  <div class="body">
    <div class="note">{{ ref_disclaimer() }}</div>
    <label for="reftype">Object type &mdash; pick a type to see public reference information</label>
    <select id="reftype" onchange="showRef(this.value)">
      <option value="">&mdash; select a type &mdash;</option>
      {% for e in ref_all() %}<option value="{{ e.object_type }}">{{ e.label }}</option>{% endfor %}
    </select>
    <div id="refpanels" style="margin-top:14px">
      {% for e in ref_all() %}
        <div class="refwrap" id="ref-{{ e.object_type }}" style="display:none">{{ ref_card(e) }}</div>
      {% endfor %}
    </div>
  </div>
</section>
</div>
<script>
function showRef(v){
  var all = document.querySelectorAll('.refwrap');
  for (var i = 0; i < all.length; i++){ all[i].style.display = 'none'; }
  if (v){ var t = document.getElementById('ref-' + v); if (t){ t.style.display = 'block'; } }
}
(function(){
  function syncGrid(){
    var m = document.querySelector('input[name="grid_mode"]:checked');
    var utm = document.getElementById('utmrow'), ll = document.getElementById('llrow');
    if (!m || !utm || !ll) return;
    var isLL = m.value === 'latlon';
    utm.style.display = isLL ? 'none' : 'flex';
    ll.style.display  = isLL ? 'flex' : 'none';
  }
  var radios = document.querySelectorAll('input[name="grid_mode"]');
  for (var i = 0; i < radios.length; i++){ radios[i].addEventListener('change', syncGrid); }
  syncGrid();
})();
</script>
<footer>Decision-support for incident link analysis — every value traces to source text; a human analyst confirms any link. Photos are filed and shown beside linked incidents for the analyst to compare — never machine-analysed.</footer>
<script src="{{ url_for('static', filename='vendor/htmx.min.js') }}"></script>
</body>
</html>"""


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
    sel = f.getlist("condition") if hasattr(f, "getlist") else []
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


@app.route("/map")
def incident_map():
    """Offline street map (map_bp.py). This only gathers the incident markers:
    an exact point when a grid was filed, otherwise the caza centre, spread so
    markers placed at the same caza do not overlap."""
    canon = {_norm(n): n for n in _CAZA_NAMES}
    centres = map_bp.caza_centres()
    meta = _load_meta()
    incidents, typecounts, percaza, unplaced = [], {}, {}, 0
    for inc in store.all_incidents():
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
        incidents.append({
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
    return map_bp.render_page(incidents, legend, unplaced=unplaced)


def _open():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    store.connect()  # ensure the DB file exists on first run
    Timer(1.2, _open).start()
    app.run(host="127.0.0.1", port=5000, debug=False)