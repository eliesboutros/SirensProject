"""The "File a new report" page (/report) and its saved confirmation.

app.py keeps the logic (reading the form, extracting, scoring, saving); this
module only lays it out:

* a side rail with the four sections, how far each is filled in, and the
  Analyse / Save buttons;
* Where and when: caza, place, date, and an offline map to drop a pin, kept
  in step with an MGRS grid reference;
* What happened: the report text;
* Object details: type as picture tiles, colour swatches, condition chips;
* Photo: drop, paste or choose, with a preview;
* after Analyse, under the form: the text with each finding highlighted, the
  findings in plain words, the matching munition reference, and one ranked
  list of linked reports with a side-by-side comparison;
* after Save, a confirmation page with the likely network and next steps.
"""
from __future__ import annotations

from flask import render_template_string

import report_view
import ui_icons


def render(**ctx):
    """ctx from app.py: mode ('form' | 'saved'), form, result, error, status,
    suggested_id, cazas, munitions, colors, conditions, sel_conditions,
    have_map, photo_name, photo_url (callable)."""
    result = ctx.get("result")
    view = {}
    if result:
        inc = result["incident"]
        groups = report_view.findings(inc)
        view = {"groups": groups, "text": report_view.highlight(inc.narrative or "", groups),
                "links": report_view.merged_links(result),
                "cards": report_view.munition_cards(result.get("reference", []))}
    return render_template_string(_TEMPLATE, view=view, icon=ui_icons.icon,
                                  mun_icon=ui_icons.MUNITION_ICON, swatch=report_view.COLOURS,
                                  **ctx)


_TEMPLATE = r"""{% import "forms_ui.html" as f %}<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens — {{ 'Report saved' if mode == 'saved' else 'File a new report' }}</title>
<link rel="stylesheet" href="{{ url_for('static', filename='sirens.css') }}">
{{ f.assets() }}
<link rel="stylesheet" href="{{ url_for('static', filename='vendor/maplibre-gl/maplibre-gl.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='report.css') }}">
</head>
<body class="rp">
<div class="bar">
  <a class="brand" href="{{ url_for('home.home_page') }}">Sirens<small>C-IED Incident Link Console</small></a>
  {{ sirens_menu('console') }}
</div>

{% macro link_list(links) %}
  {% if links %}
  <ol class="links">
    {% for r in links %}
    <li class="lk">
      <div class="lk-top">
        {% if r.band %}<span class="band {{ r.band }}">{{ r.band|capitalize }}</span>
        {% else %}<span class="band wording">Wording only</span>{% endif %}
        <span class="lk-id mono">{{ r.inc.incident_id }}</span>
        <span class="lk-where">{{ r.inc.location or 'No location' }}{% if r.inc.date %}, {{ r.inc.date }}{% endif %}</span>
        {% if r.score is not none %}<span class="lk-score num" title="Link score from shared features and people">{{ '%.2f'|format(r.score) }}</span>{% endif %}
      </div>
      {% if r.shares %}<p class="lk-why"><span>Shares</span> {{ r.shares|join(', ') }}</p>{% endif %}
      {% if r.near %}<p class="lk-why"><span>Place</span> {{ r.near|join('; ') }}</p>{% endif %}
      {% if r.wording is not none %}<p class="lk-why"><span>Wording</span> {{ 'very similar' if r.wording_band == 'strong' else 'similar' if r.wording_band == 'medium' else 'somewhat similar' }} ({{ '%.2f'|format(r.wording) }})</p>{% endif %}
      <details class="cmp">
        <summary>Compare the two reports</summary>
        <div class="cmp-cols">
          <div><h4>This report</h4><p dir="auto">{{ view.text }}</p></div>
          <div><h4>{{ r.inc.incident_id }}{% if r.inc.date %}, {{ r.inc.date }}{% endif %}</h4><p dir="auto">{{ r.compare }}</p>
            {% set hp = photo_url(r.inc) %}{% if hp %}<a href="{{ hp }}" target="_blank" rel="noopener"><img class="cmp-img" src="{{ hp }}" alt="Photo on file for {{ r.inc.incident_id }}"></a>{% endif %}</div>
        </div>
      </details>
    </li>
    {% endfor %}
  </ol>
  {% else %}<p class="muted">No past report shares features, people or wording with this one.</p>{% endif %}
{% endmacro %}

{% macro findings_block() %}
  <div class="fd">
    <div class="fd-text">
      <h3>The report, with what Sirens read marked</h3>
      <p class="marked" dir="auto">{{ view.text }}</p>
      <div class="legend" aria-label="Colour key">
        {% for g in view.groups %}<span><i class="hl hl-{{ g.group }}"></i>{{ g.title }}</span>{% endfor %}
      </div>
    </div>
    <div class="fd-list">
      {% for g in view.groups %}
        <h3>{{ g.title }}</h3>
        <dl>{% for it in g['items'] %}<div><dt>{{ it.label }}</dt><dd>{{ it.value }}</dd></div>{% endfor %}</dl>
      {% else %}<p class="muted">Sirens found no descriptive features in this text. Links can still come from similar wording.</p>{% endfor %}
    </div>
  </div>
  {% for c in view.cards %}
  <a class="mref" href="{{ url_for('munitions.munitions_page') }}#ref-{{ c.object_type }}">
    <span class="icon">{{ icon(c.family) }}</span>
    <span><strong>{{ c.label }}</strong><span class="famname">{{ c.family_name }}, in the munitions reference</span>
      {% if c.summary %}<span class="sum">{{ c.summary }}</span>{% endif %}
      {% if c.responder_note %}<span class="rnote">{{ c.responder_note }}</span>{% endif %}</span>
  </a>
  {% endfor %}
{% endmacro %}

{% if mode == 'saved' %}
{# ------------------------------------------------------------------ saved #}
{% set inc = result.incident %}{% set m = result.meta %}
<main class="wrap saved">
  <div class="f-saved" role="status">Saved <strong class="mono">{{ inc.incident_id }}</strong> to the record.</div>
  <h1>{{ inc.incident_id }} is on record</h1>
  <p class="lead">{{ [inc.location, inc.date]|select|join(', ') or 'No place or date given' }}.
    {% if m.grid_mgrs %}Grid <span class="mono">{{ m.grid_mgrs }}</span>.{% endif %}
    {% if m.munition_label %}Type: {{ m.munition_label }}.{% endif %}</p>
  <div class="next">
    <a class="btn" href="{{ url_for('index') }}">File another report</a>
    <a class="btn ghost" href="{{ url_for('review.review_page', show='open') }}">Review links</a>
    <a class="btn ghost" href="{{ url_for('incident_map') }}">See it on the map</a>
  </div>

  <section class="panel">
    <div class="net" hx-get="{{ url_for('network.panel', incident_id=inc.incident_id) }}" hx-trigger="load" hx-swap="innerHTML">
      <h2>Likely network</h2><p class="muted">Working out its network…</p></div>
  </section>

  <section class="panel">
    <h2>What Sirens read</h2>
    {{ findings_block() }}
  </section>

  <section class="panel">
    <h2>Linked reports <span class="h-note">Leads for an analyst to check, not conclusions</span></h2>
    {{ link_list(view.links) }}
  </section>
</main>
<script src="{{ url_for('static', filename='vendor/htmx.min.js') }}"></script>

{% else %}
{# ------------------------------------------------------------------- form #}
<form class="f-form" id="rp-form" method="post" action="/analyse" enctype="multipart/form-data" novalidate>
<div class="rp-grid wrap">
  <aside class="rail" aria-label="Report sections">
    <h1>File a new report</h1>
    <ol class="steps">
      <li><a href="#s-where" data-step="where">Where and when</a></li>
      <li><a href="#s-what" data-step="what">What happened</a></li>
      <li><a href="#s-details" data-step="details">Object details</a></li>
      <li><a href="#s-photo" data-step="photo">Photo</a></li>
      {% if result %}<li><a href="#results" class="res">What Sirens found</a></li>{% endif %}
    </ol>
    <div class="rail-actions">
      <button class="f-btn" type="submit" name="action" value="save" data-busy-text="Saving…">Save report</button>
      <button class="f-btn ghost" type="submit" name="action" value="analyse" data-busy-text="Analysing…">Analyse first</button>
      <p class="rail-hint">Analyse shows what Sirens reads and links without saving. Your text stays in the form.</p>
      {{ f.toggle("use_ai", "AI summary", "use_ai", checked=(form.use_ai == 'on' if form else status.ai_ok) and status.ai_ok, disabled=not status.ai_ok,
                  note=('' if status.ai_ok else 'Off: the local AI model is not running.')) }}
    </div>
  </aside>

  <div class="main">
    {{ f.form_error(error) }}

    <section class="sec" id="s-where" aria-labelledby="h-where">
      <h2 id="h-where">Where and when</h2>
      <div class="f-grid">
        {{ f.input("incident_id", "Incident ID", "incident_id", value=(form.incident_id or suggested_id), mono=True) }}
        {{ f.input("date", "Date", "date", value=form.date, placeholder="2026-11-03", rules="date-advisory", optional=True) }}
        {{ f.select("caza", "Caza (district)", "caza", cazas, selected=form.caza, blank="Choose a caza", optional=True) }}
        {{ f.input("street", "Town, village or street", "street", value=form.street, placeholder="e.g. Khiam, main road",
                   list="placelist", rules="place:placelist:caza", optional=True) }}
        <datalist id="placelist">{% for pl in map_places() %}<option value="{{ pl }}">{% endfor %}</datalist>
      </div>
      <div class="pick">
        <div id="pickmap" class="pickmap" role="application" aria-label="Map: click to place the report"
             data-have-map="{{ 1 if have_map else 0 }}" data-style="{{ url_for('static', filename='map/style.json') }}"
             data-tiles="{{ url_for('offmap.pmtiles_file') }}" data-cazas="{{ url_for('offmap.cazas_geojson') }}"></div>
        <div class="pick-side">
          {{ f.input("mgrs", "Grid reference (MGRS)", "mgrs", value=form.mgrs, placeholder="36S YB 049 833", mono=True, optional=True) }}
          <input type="hidden" id="lat" name="lat" value="{{ form.lat or '' }}">
          <input type="hidden" id="lon" name="lon" value="{{ form.lon or '' }}">
          <input type="hidden" name="grid_mode" value="latlon">
          <p class="pick-note" id="pick-note">{{ 'Click the map to place the report, or type a grid reference.' }}</p>
          <button type="button" class="linkbtn" id="pick-clear" {{ '' if form.mgrs or form.lat else 'hidden' }}>Remove the pin</button>
        </div>
      </div>
    </section>

    <section class="sec" id="s-what" aria-labelledby="h-what">
      <h2 id="h-what">What happened</h2>
      <div class="f-grid">
        {{ f.textarea("narrative", "Report text", "narrative", value=form.narrative, rows=9, rules="required",
                      placeholder="Paste or type the report as received. Messy field wording is fine.",
                      required_msg="Paste the report text: it is what Sirens reads.") }}
      </div>
    </section>

    <section class="sec" id="s-details" aria-labelledby="h-details">
      <h2 id="h-details">Object details <span class="opt">optional</span></h2>
      <div class="f-field f-wide" role="group" aria-labelledby="l-munition">
        {{ f.label("munition", "Type", "munition", tag='span') }}
        <div class="tiles">
          <label class="tile"><input type="radio" name="munition" value=""{{ ' checked' if not form.munition }}>
            <span class="t-ic">{{ icon('other') }}</span><span>Not sure</span></label>
          {% for k, label, colour in munitions %}{% if k != 'other' %}
          <label class="tile"><input type="radio" name="munition" value="{{ k }}"{{ ' checked' if form.munition == k }}>
            <span class="t-ic" style="--mk:{{ colour }}">{{ icon(mun_icon.get(k, 'other')) }}</span><span>{{ label }}</span></label>
          {% endif %}{% endfor %}
        </div>
      </div>
      <div class="f-field f-wide" role="group" aria-labelledby="l-item_color">
        {{ f.label("item_color", "Colour", "item_color", tag='span') }}
        <div class="swatches">
          <label class="sw"><input type="radio" name="item_color" value=""{{ ' checked' if not form.item_color }}><span class="chip none">Not stated</span></label>
          {% for c in colors %}
          <label class="sw"><input type="radio" name="item_color" value="{{ c }}"{{ ' checked' if form.item_color == c }}>
            <span class="chip"><i style="background:{{ swatch.get(c, '#ccc') }}"></i>{{ c }}</span></label>
          {% endfor %}
        </div>
      </div>
      <div class="f-grid">
        {{ f.input("item_color_other", "Other colour or markings", "item_color_other", value=form.item_color_other, placeholder="e.g. green with white stencil", optional=True, wide=True) }}
        {{ f.choices("condition", "Condition", "condition", conditions, checked=sel_conditions, optional=True) }}
      </div>
    </section>

    <section class="sec" id="s-photo" aria-labelledby="h-photo">
      <h2 id="h-photo">Photo <span class="opt">optional</span></h2>
      <div class="f-field f-wide">
        {{ f.label("photo_file", "Photo of the scene or object", "photo_file", optional=True) }}
        <label class="drop" id="drop">
          <input type="file" id="photo_file" name="photo_file" accept="image/*" aria-describedby="e-photo_file">
          <span class="drop-empty">{{ icon('report') }}<strong>Drop a photo here, paste it, or choose a file</strong>
            <span>JPG, PNG, WEBP or GIF, up to 8 MB. Kept for comparison by an analyst, never analysed.</span></span>
          <span class="drop-full" hidden><img id="drop-img" alt="Selected photo"><span id="drop-name"></span></span>
        </label>
        <div class="f-error" id="e-photo_file" aria-live="polite"></div>
        <button type="button" class="linkbtn" id="drop-clear" hidden>Remove the photo</button>
        {% if photo_name %}
          <input type="hidden" name="photo" value="{{ photo_name }}">
          <p class="kept">Photo already attached: <a href="{{ url_for('photo', name=photo_name) }}" target="_blank" rel="noopener">{{ photo_name }}</a>. Choose another to replace it.</p>
        {% endif %}
      </div>
    </section>

    {% if result %}
    <section class="results" id="results" aria-labelledby="h-results">
      <h2 id="h-results">What Sirens found <span class="h-note">Not saved yet. Press Save report to file it.</span></h2>
      {% if result.assessment %}<div class="ai"><h3>AI summary</h3><p>{{ result.assessment }}</p></div>{% endif %}
      {{ findings_block() }}
      <h3 class="lk-h">Linked reports <span class="h-note">Leads for an analyst to check, not conclusions</span></h3>
      {{ link_list(view.links) }}
    </section>
    {% endif %}

    <div class="mobile-actions">
      <button class="f-btn" type="submit" name="action" value="save" data-busy-text="Saving…">Save report</button>
      <button class="f-btn ghost" type="submit" name="action" value="analyse" data-busy-text="Analysing…">Analyse first</button>
    </div>
  </div>
</div>
</form>
<script src="{{ url_for('static', filename='vendor/mgrs/mgrs.min.js') }}"></script>
<script src="{{ url_for('static', filename='vendor/pmtiles/pmtiles.js') }}"></script>
<script type="module" src="{{ url_for('static', filename='report.js') }}"></script>
{% if result %}<script>addEventListener('DOMContentLoaded', function(){ var r = document.getElementById('results'); if (r) r.scrollIntoView(); });</script>{% endif %}
{% endif %}
<footer>Decision support only. Every finding traces to the report text, and a person confirms every link.</footer>
</body>
</html>
"""
