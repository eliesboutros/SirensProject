"""Shared form building blocks: one design for every form in Sirens.

register(app, map_places) adds a Jinja template "forms_ui.html" holding the
macros below, plus two helpers every template can call:
  form_help(key)   the help text for a field (all wording lives in HELP)
  map_places()     place names the map can position (for location suggestions)

Pages import the macros with:
  {% import "forms_ui.html" as f %}
and get the stylesheet and script with {{ f.assets() }} (static/forms.css,
static/forms.js; local files only, no network).

Field names, routes and parameters are never changed here: the macros only
render the markup around the same <input name="..."> the backend already reads.
"""
from __future__ import annotations

from jinja2 import ChoiceLoader, DictLoader

# Help text for every field, in one place so the wording can be reviewed.
# Descriptive, analyst-level language only. The brief retrieves and ranks past
# reporting; nothing here identifies an object or advises on approach/handling.
HELP = {
    # --- New report (console) -------------------------------------------------
    "incident_id": "A unique reference for this report. Sirens suggests the next free number; "
                   "saving again under the same reference replaces that record.",
    "date": "The date of the incident, written as YYYY-MM-DD (for example 2026-03-04). "
            "Used for the timeline and for ordering past reports.",
    "caza": "The district the incident happened in. This is what places the report on the map "
            "when no grid reference is given.",
    "street": "The town, village, street or landmark as written in the report. Suggestions are "
              "places the map already knows; other names are kept as written.",
    "narrative": "The free-text report. Sirens reads it to pick out descriptive features, names, "
                 "groups and phone numbers, and compares them with past reports. Required.",
    "munition": "The reported category of item. It sets the colour of the report's marker on the "
                "map; if left empty, Sirens guesses a category from the narrative.",
    "item_color": "Colour or markings as described in the report (for example olive, rust). "
                  "Kept with the record for comparison; it is not used to score links.",
    "condition": "How the item was described (buried, corroded and so on). Tick all that apply. "
                 "Kept with the record; it is not used to score links.",
    "grid_mode": "Choose how the grid reference is written: UTM easting/northing or "
                 "latitude/longitude in decimal degrees.",
    "utm_zone": "Lebanon spans UTM zones 36 (coast and most of the country) and 37 "
                "(eastern Beqaa and Baalbek-Hermel), split at 36°E.",
    "utm_e": "UTM easting in metres, between 100000 and 900000. Give it together with the northing.",
    "utm_n": "UTM northing in metres. Give it together with the easting.",
    "lat": "Latitude in decimal degrees (for example 33.27). Give it together with the longitude.",
    "lon": "Longitude in decimal degrees (for example 35.20). Give it together with the latitude.",
    "photo_file": "An optional image filed with the record and shown beside linked incidents for "
                  "visual comparison by an analyst. It is not analysed. JPG, PNG, WEBP or GIF, up to 8 MB.",
    "use_ai": "Ask the local AI model (Ollama, on this machine) for a short written summary of the "
              "links found. A human analyst confirms every link; off when Ollama is not running.",
    # --- Pre-arrival brief ----------------------------------------------------
    "brief_location": "The place to brief on. Sirens retrieves past reports recorded at or near "
                      "this place and ranks them; suggestions are places already in the record.",
    "brief_describe": "Optional words from a description. They are used only to rank past reports "
                      "by how closely their recorded descriptions match. This does not identify "
                      "anything and gives no advice on what to do.",
    "brief_use_ai": "Ask the local AI model for a short summary of the past reporting retrieved for "
                    "this place. Off when Ollama is not running.",
    # --- Review links ---------------------------------------------------------
    "analyst": "Optional initials stored with your decisions and notes, so a team can see who "
               "recorded what. Remembered in this browser only.",
    "note": "A short analyst note on this link (for example why it was rejected). Notes are kept "
            "with the link's history and never change the machine's score.",
    # --- Dashboard filters ----------------------------------------------------
    "from": "Show only incidents on or after this date. Reports without a date are left out "
            "while a date range is set.",
    "to": "Show only incidents on or before this date.",
    "area": "Show only incidents recorded at this place.",
    "initiation": "Show only incidents whose reports mention this initiation method.",
    "feature": "Show only incidents whose reports mention this descriptive feature.",
    "facet": "Choose which descriptive feature the chart below counts. This only changes the "
             "chart; use the filters above to narrow the whole page.",
}


def form_help(key: str) -> str:
    return HELP.get(key, "")


MACROS = r"""
{% macro assets() -%}
<link rel="stylesheet" href="{{ url_for('static', filename='forms.css') }}">
<script src="{{ url_for('static', filename='forms.js') }}" defer></script>
{%- endmacro %}

{% macro help(key, label, for_id) -%}
<button type="button" class="f-help" data-for="{{ for_id }}" aria-label="Help: {{ label }}"
        aria-expanded="false" aria-controls="h-{{ for_id }}">i</button>
<span class="f-tip" role="tooltip" id="h-{{ for_id }}" hidden>{{ form_help(key) }}</span>
{%- endmacro %}

{% macro label(for_id, text, key, optional=False, tag='label') -%}
<div class="f-labelrow">
  <{{ tag }} class="f-label"{% if tag == 'label' %} for="{{ for_id }}"{% else %} id="l-{{ for_id }}"{% endif %}>{{ text }}{% if optional %} <span class="f-opt">optional</span>{% endif %}</{{ tag }}>
  {{ help(key, text, for_id) }}
</div>
{%- endmacro %}

{# A text-like input. rules: space-separated data rules read by forms.js:
   required, number, date-advisory, pair:<other id>, range:<min>,<max>, place:<datalist id> #}
{% macro input(name, text, key, value='', id=None, type='text', placeholder='', rules='',
               optional=False, list=None, mono=False, inputmode=None, extra='', wide=False, required_msg='', place_msg='') -%}
{% set fid = id or name %}
<div class="f-field{{ ' f-wide' if wide else '' }}">
  {{ label(fid, text, key, optional) }}
  <input class="f-input{{ ' f-mono' if mono else '' }}" type="{{ type }}" id="{{ fid }}" name="{{ name }}"
         value="{{ value or '' }}"{% if placeholder %} placeholder="{{ placeholder }}"{% endif %}
         {% if type in ('text', 'search') %}dir="auto"{% endif %}{% if list %} list="{{ list }}"{% endif %}
         {% if inputmode %} inputmode="{{ inputmode }}"{% endif %}{% if rules %} data-rules="{{ rules }}"{% endif %}
         aria-describedby="e-{{ fid }}"{% if 'required' in rules.split() %} aria-required="true"{% endif %}
         {% if required_msg %} data-required-msg="{{ required_msg }}"{% endif %}{% if place_msg %} data-place-msg="{{ place_msg }}"{% endif %} {{ extra|safe }}>
  <div class="f-error" id="e-{{ fid }}" aria-live="polite"></div>
</div>
{%- endmacro %}

{% macro textarea(name, text, key, value='', id=None, placeholder='', rules='', optional=False, rows=6, required_msg='') -%}
{% set fid = id or name %}
<div class="f-field f-wide">
  {{ label(fid, text, key, optional) }}
  <textarea class="f-input" id="{{ fid }}" name="{{ name }}" dir="auto" rows="{{ rows }}"
            {% if placeholder %}placeholder="{{ placeholder }}"{% endif %}{% if rules %} data-rules="{{ rules }}"{% endif %}
            aria-describedby="e-{{ fid }}"{% if 'required' in rules.split() %} aria-required="true"{% endif %}
            {% if required_msg %} data-required-msg="{{ required_msg }}"{% endif %}>{{ value or '' }}</textarea>
  <div class="f-error" id="e-{{ fid }}" aria-live="polite"></div>
</div>
{%- endmacro %}

{# options: list of strings, or of (value, label, ...) tuples #}
{% macro select(name, text, key, options, selected='', id=None, blank=None, optional=False, extra='') -%}
{% set fid = id or name %}
<div class="f-field">
  {{ label(fid, text, key, optional) }}
  <select class="f-input" id="{{ fid }}" name="{{ name }}" aria-describedby="e-{{ fid }}" {{ extra|safe }}>
    {% if blank is not none %}<option value="">{{ blank }}</option>{% endif %}
    {% for o in options %}{% set v = o if o is string else o[0] %}{% set l = o if o is string else o[1] %}<option value="{{ v }}"{{ ' selected' if v == selected else '' }}>{{ l }}</option>{% endfor %}
  </select>
  <div class="f-error" id="e-{{ fid }}" aria-live="polite"></div>
</div>
{%- endmacro %}

{# A group of checkboxes or radios sharing one name. options as for select #}
{% macro choices(name, text, key, options, checked=(), kind='checkbox', id=None, optional=False) -%}
{% set fid = id or name %}
<div class="f-field f-wide" role="group" aria-labelledby="l-{{ fid }}">
  {{ label(fid, text, key, optional, tag='span') }}
  <div class="f-choices" id="{{ fid }}">
    {% for o in options %}{% set v = o if o is string else o[0] %}{% set l = o if o is string else o[1] %}
    <label class="f-choice"><input type="{{ kind }}" name="{{ name }}" value="{{ v }}"{{ ' checked' if v in checked else '' }}> <span>{{ l }}</span></label>
    {% endfor %}
  </div>
</div>
{%- endmacro %}

{% macro toggle(name, text, key, checked=False, disabled=False, note='', id=None) -%}
{% set fid = id or name %}
<div class="f-field f-togglefield">
  <div class="f-labelrow">
    <label class="f-toggle{{ ' is-disabled' if disabled else '' }}" for="{{ fid }}">
      <input type="checkbox" id="{{ fid }}" name="{{ name }}"{{ ' checked' if checked else '' }}{{ ' disabled' if disabled else '' }}>
      <span>{{ text }}</span>
    </label>
    {{ help(key, text, fid) }}
  </div>
  {% if note %}<div class="f-hint">{{ note }}</div>{% endif %}
</div>
{%- endmacro %}

{% macro section(title, sub='') -%}
<fieldset class="f-section">
  <legend class="f-legend">{{ title }}</legend>
  {% if sub %}<p class="f-sub">{{ sub }}</p>{% endif %}
  <div class="f-grid">{{ caller() }}</div>
</fieldset>
{%- endmacro %}

{# Collapsed by default; opens if any field inside has a value (open=True) or,
   in the browser, as soon as a field inside shows an error. #}
{% macro more(title='More details', open=False, sub='') -%}
<details class="f-more"{{ ' open' if open else '' }}>
  <summary class="f-more-sum">{{ title }}{% if sub %} <span class="f-opt">{{ sub }}</span>{% endif %}</summary>
  <div class="f-grid">{{ caller() }}</div>
</details>
{%- endmacro %}

{% macro form_error(message, lead='Not saved.') -%}
{% if message %}<div class="f-alert" role="alert"><strong>{{ lead }}</strong> {{ message }}</div>{% endif %}
{%- endmacro %}

{# chips: list of (label, remove_url). clear_url resets every filter. #}
{% macro chips(active, clear_url) -%}
{% if active %}
<div class="f-chips" aria-label="Active filters">
  {% for text, url in active %}<a class="f-chip" href="{{ url }}" aria-label="Remove filter: {{ text }}">{{ text }} <span aria-hidden="true">&times;</span></a>{% endfor %}
  <a class="f-clear" href="{{ clear_url }}">Clear all</a>
</div>
{% endif %}
{%- endmacro %}
"""


def register(app, map_places=None) -> None:
    """Make the macros importable as "forms_ui.html" and expose the helpers."""
    app.jinja_loader = ChoiceLoader([DictLoader({"forms_ui.html": MACROS}), app.jinja_loader])
    app.jinja_env.globals["form_help"] = form_help
    app.jinja_env.globals["map_places"] = map_places or (lambda: [])
    app.register_error_handler(404, _error_page(404))
    app.register_error_handler(413, _error_page(413))
    app.register_error_handler(500, _error_page(500))


_ERRORS = {
    404: ("Page not found", "That address does not exist in Sirens."),
    413: ("File too large", "The upload is larger than 8 MB, so nothing was saved. "
                            "Go back, choose a smaller photo (or none), and save again."),
    500: ("Something went wrong", "Sirens could not finish that request and nothing new was saved. "
                                  "Go back and try again; if it keeps happening, note what you did."),
}


def _error_page(code):
    def handler(err):
        from flask import render_template_string, request
        # htmx requests get a short message the page shows next to the form.
        title, text = _ERRORS[code]
        if request.headers.get("HX-Request"):
            return f"{title}. {text}", code
        return render_template_string(_ERROR_TEMPLATE, title=title, text=text, code=code), code
    return handler


_ERROR_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens — {{ title }}</title>
<style>
  body{margin:0;background:#f4f6f3;color:#16202b;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .bar{display:flex;align-items:center;gap:20px;flex-wrap:wrap;padding:18px 32px;background:#16202b;color:#eef2f5;border-bottom:3px solid #a8703a}
  .brand{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-weight:600;letter-spacing:.16em;text-transform:uppercase;font-size:15px}
  .brand small{display:block;letter-spacing:.06em;font-size:10px;color:#9fb0bd;font-weight:400;margin-top:2px}
  .wrap{max-width:720px;margin:0 auto;padding:56px 32px}
  .card{background:#fff;border:1px solid #e2e6e3;border-radius:10px;padding:28px 30px;box-shadow:0 1px 2px rgba(22,32,43,.04),0 4px 16px rgba(22,32,43,.05)}
  h1{font-size:19px;margin:0 0 10px}
  p{margin:0 0 18px;color:#3a4652}
  a.btn{display:inline-block;font-weight:600;font-size:14px;padding:9px 16px;border-radius:6px;background:#16202b;color:#fff;text-decoration:none;margin-right:10px}
  a.ghost{background:#fff;color:#16202b;border:1px solid #c9d0cb}
</style></head><body>
<div class="bar"><div class="brand">Sirens<small>{{ title|lower }}</small></div>{{ sirens_menu('') }}</div>
<div class="wrap"><div class="card" role="alert">
  <h1>{{ title }}</h1><p>{{ text }}</p>
  <a class="btn" href="javascript:history.back()">Go back</a><a class="btn ghost" href="{{ url_for('index') }}">New report</a>
</div></div></body></html>
"""

