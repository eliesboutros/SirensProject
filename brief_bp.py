"""Web routes for the record-based pre-arrival brief.

A standalone Flask Blueprint so this feature can be wired into app.py with a
two-line import/registration, rather than another edit to the large app.py
template string. Retrieval-only: never identifies what's in front of the
responder, never gives handling/render-safe guidance — see linker/query.py.
"""
from __future__ import annotations

import pathlib

from flask import Blueprint, render_template_string, request

from linker import store, ai
from linker.extract import FeatureExtractor
from linker.query import area_brief

ROOT = pathlib.Path(__file__).resolve().parent
TAXONOMY = ROOT / "data" / "taxonomy" / "cied_lexicon.json"

brief_bp = Blueprint("brief", __name__)
_EXTRACTOR = FeatureExtractor(TAXONOMY, use_ner=True)


@brief_bp.route("/brief", methods=["GET", "POST"])
def brief_page():
    result = None
    error = None
    form = {}
    assessment = None
    if request.method == "POST":
        location = (request.form.get("location") or "").strip()
        describe = (request.form.get("describe") or "").strip() or None
        use_ai = request.form.get("use_ai") == "on"
        form = {"location": location, "describe": describe or "", "use_ai": use_ai}
        if not location:
            error = "Enter a location to brief on — e.g. a town or street name used in your reports."
        else:
            incidents = store.all_incidents()
            result = area_brief(incidents, location=location, describe=describe,
                                 extractor=_EXTRACTOR)
            if use_ai:
                assessment = ai.assess_area(result)
    all_locations = sorted({i.location for i in store.all_incidents() if i.location})
    ai_ok, ai_reason = ai.available()
    return render_template_string(_TEMPLATE, brief=result, form=form, error=error,
                                   db_count=store.count(), locations=all_locations,
                                   assessment=assessment, ai_ok=ai_ok, ai_reason=ai_reason)


_TEMPLATE = r"""{% import "forms_ui.html" as f %}<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens — Pre-arrival Brief</title>
<style>
  :root{
    --ink:#16202b; --ink-soft:#3a4652; --line:#e2e6e3; --line-2:#eef0ee;
    --surface:#f4f6f3; --panel:#ffffff; --sig:#a8703a; --sig-soft:#f0e6d4;
    --weak:#7a8791; --link:#2d5b8e;
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
  .bar a{margin-left:auto;color:#cdd8e0;font-family:var(--mono);font-size:11px;
    text-decoration:none;border:1px solid #2c3c4a;padding:5px 10px;border-radius:2px}
  .wrap{max-width:1600px;margin:0 auto;padding:40px 48px 90px}
  .grid{display:grid;grid-template-columns:minmax(0,500px) minmax(0,1fr);gap:40px;align-items:start}
  @media(max-width:1000px){.wrap{padding:28px 20px 60px}.grid{grid-template-columns:1fr}}
  @media(max-width:840px){.grid{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:9px;
        box-shadow:0 1px 2px rgba(22,32,43,.04),0 4px 16px rgba(22,32,43,.05)}
  .card h2{margin:0;padding:14px 18px;border-bottom:1px solid var(--line-2);
           font-size:12px;letter-spacing:.14em;text-transform:uppercase;
           color:var(--ink-soft);font-family:var(--mono);font-weight:600}
  .card .body{padding:24px 26px}
  label{display:block;font-size:12px;letter-spacing:.03em;color:var(--ink-soft);
        margin:0 0 5px;font-weight:600}
  input[type=text],textarea,select{width:100%;padding:9px 11px;border:1px solid var(--line);
        border-radius:4px;font-family:var(--sans);font-size:14px;color:var(--ink);
        background:#fcfdfc}
  textarea{min-height:150px;resize:vertical;line-height:1.6}
  .field{margin-bottom:14px}
  .hint{font-size:12px;color:var(--weak);margin-top:5px}
  .btn{font-family:var(--sans);font-size:14px;font-weight:600;padding:10px 16px;
       border-radius:4px;border:1px solid var(--ink);background:var(--ink);
       color:#fff;cursor:pointer}
  .btn:hover{background:#22303d}
  .err{background:#fbeceb;border:1px solid #e7b7b2;color:#a4332b;padding:10px 14px;
       border-radius:4px;font-size:13px;margin-bottom:14px}
  .note{font-size:12.5px;color:var(--ink-soft);background:var(--line-2);
        border-radius:4px;padding:9px 12px;margin-bottom:14px}
  .empty{color:var(--weak);font-size:14px;padding:8px 2px}
  .stat{font-family:var(--mono);font-size:12px;color:var(--ink-soft)}
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
  .chip{font-family:var(--mono);font-size:11.5px;padding:3px 8px;border-radius:3px;
        background:var(--sig-soft);color:#7a4e12;border:1px solid #e6d3b0}
  table.profile{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
  table.profile th{text-align:left;font-weight:600;color:var(--ink-soft);
        padding:4px 10px 4px 0;border-bottom:1px solid var(--line-2)}
  table.profile td{padding:5px 10px 5px 0;border-bottom:1px solid var(--line-2)}
  .match{border:1px solid var(--line);border-left:4px solid var(--sig);border-radius:5px;
        padding:12px 14px;margin-bottom:10px;background:#fff}
  .match .top{display:flex;align-items:center;gap:10px}
  .score{font-family:var(--mono);font-weight:700;font-size:13px;padding:3px 8px;
         border-radius:3px;background:var(--sig-soft);color:#7a4e12}
  .mid{font-family:var(--mono);font-weight:600;font-size:13px}
  .loc{color:var(--weak);font-size:12.5px;margin-left:auto;text-align:right}
  .subhead{font-size:11px;letter-spacing:.12em;text-transform:uppercase;
           color:var(--weak);font-family:var(--mono);margin:16px 0 8px}
  .subhead:first-child{margin-top:0}
</style>
{{ f.assets() }}
</head>
<body>
<div class="bar">
  <div class="brand">Sirens<small>Pre-arrival Brief</small></div>
  {{ sirens_menu('brief') }}
</div>
<div class="wrap">
  <div class="grid">
    <section class="card">
      <h2>Query</h2>
      <div class="body">
        <form class="f-form" method="post" action="/brief" novalidate>
          {{ f.form_error(error, lead='Brief not run.') }}
          {% call f.section("Place", sub="Sirens retrieves and ranks past reporting recorded at or near this place.") %}
            {{ f.input("location", "Location", "brief_location", id="location", value=form.location, list="recordplaces",
                       placeholder="e.g. Yaroun", rules="required place:recordplaces", wide=True,
                       required_msg="Enter a place to brief on.",
                       place_msg="This place is not in the record yet; the brief may find no past reporting.") }}
            <datalist id="recordplaces">{% for loc in locations %}<option value="{{ loc }}">{% endfor %}</datalist>
          {% endcall %}
          {% call f.more("More details", open=(form.describe or false), sub="compare with a description") %}
            {{ f.textarea("describe", "Description to compare with", "brief_describe", value=form.describe, optional=True, rows=4,
                          placeholder="e.g. small green fin-stabilised rocket, intact, about 1 m") }}
          {% endcall %}
          <div class="f-actions">
            <button class="f-btn" type="submit" data-busy-text="Retrieving…">Get brief</button>
            {{ f.toggle("use_ai", "AI area summary", "brief_use_ai", checked=form.use_ai, disabled=not ai_ok,
                        note=('' if ai_ok else 'Off: ' ~ ai_reason)) }}
          </div>
        </form>
        <div class="stat" style="margin-top:16px">{{ db_count }} incidents on record.</div>
      </div>
    </section>

    <section>
      {% if not brief %}
        <div class="card"><div class="body">
          <p class="empty">Enter a location on the left to see what the record says about that
            area — object types reported there, the device signature that tends to
            co-occur, and (optionally) the closest past records to a description.</p>
        </div></div>
      {% else %}
        <div class="card">
          <h2>Record for &ldquo;{{ brief.location_query }}&rdquo;
            <a href="/map" style="float:right;font-family:var(--mono);font-size:10.5px;color:var(--link);text-decoration:none">view full map &#8599;</a></h2>
          <div class="body">
            <div class="note">{{ brief.note }}</div>
            <div class="stat">{{ brief.n_in_area }} incident{{ '' if brief.n_in_area == 1 else 's' }} on record in this area.</div>

            <div class="subhead">Object types seen here</div>
            {% if brief.object_profile %}
              <table class="profile">
                <tr><th>Type</th><th>Count</th><th>Most recent</th></tr>
                {% for t, c, recent in brief.object_profile %}
                <tr><td>{{ t }}</td><td>{{ c }}</td><td>{{ recent or '—' }}</td></tr>
                {% endfor %}
              </table>
            {% else %}<div class="empty">No object-type reporting on record for this area.</div>{% endif %}

            <div class="subhead">Co-occurring device signature</div>
            {% if brief.area_signature %}
              <div class="chips">{% for s in brief.area_signature %}<span class="chip">{{ s }}</span>{% endfor %}</div>
            {% else %}<div class="empty">No dominant shared signature for this area.</div>{% endif %}
          </div>
        </div>

        {% if brief.area_incidents %}
        <div class="card" style="margin-top:16px">
          <h2>Incidents on record here ({{ brief.area_incidents|length }})</h2>
          <div class="body">
            {% for inc in brief.area_incidents %}
            <div class="match">
              <div class="top">
                <span class="mid">{{ inc.incident_id }}</span>
                <span class="loc">{{ inc.location or '—' }}{% if inc.date %} &middot; {{ inc.date }}{% endif %}</span>
              </div>
              <div style="font-size:13px;color:var(--ink-soft);margin-top:6px;line-height:1.5">
                {{ inc.narrative[:220] }}{% if inc.narrative|length > 220 %}&hellip;{% endif %}
              </div>
              {% if inc.features %}
              <div class="chips" style="margin-top:8px">
                {% for f in inc.features[:6] %}<span class="chip">{{ f.facet }}={{ f.value }}</span>{% endfor %}
              </div>
              {% endif %}
              {% if inc.persons or inc.groups or inc.phones %}
              <div class="chips" style="margin-top:5px">
                {% for p in inc.persons %}<span class="chip" style="background:#e9eef4;color:#274a6e;border-color:#cdd9e6">person: {{ p }}</span>{% endfor %}
                {% for g in inc.groups %}<span class="chip" style="background:#e9eef4;color:#274a6e;border-color:#cdd9e6">group: {{ g }}</span>{% endfor %}
                {% for ph in inc.phones %}<span class="chip" style="background:#e9eef4;color:#274a6e;border-color:#cdd9e6">phone: {{ ph }}</span>{% endfor %}
              </div>
              {% endif %}
              {% set purl = photo_url(inc) %}
              {% if purl %}
              <a href="{{ purl }}" target="_blank" rel="noopener" style="display:block;margin-top:8px">
                <img src="{{ purl }}" alt="Photo for {{ inc.incident_id }}" style="max-height:140px;border:1px solid var(--line);border-radius:5px">
              </a>
              {% endif %}
            </div>
            {% endfor %}
          </div>
        </div>
        {% endif %}

        {% if assessment %}
        <div class="card" style="margin-top:16px">
          <h2>AI area summary
            {% if assessment.ok %}<span style="font-family:var(--mono);font-size:10px;background:#2d5b8e;color:#fff;padding:2px 7px;border-radius:2px;margin-left:8px">{{ assessment.model }}</span>{% endif %}</h2>
          <div class="body">
            {% if assessment.ok %}
              <div style="font-size:14px;line-height:1.6">{{ assessment.text }}</div>
              <div class="hint" style="border-top:1px solid var(--line-2);padding-top:9px;margin-top:10px">
                Generated by a small local model — verify against the tables above before acting on it.
              </div>
            {% else %}
              <div class="empty">Assessment unavailable — {{ assessment.reason }}</div>
            {% endif %}
          </div>
        </div>
        {% endif %}

        {% if brief.describe_query %}
        <div class="card" style="margin-top:16px">
          <h2>Closest past records to the description</h2>
          <div class="body">
            {% if brief.matches %}
              {% for m in brief.matches %}
              <div class="match">
                <div class="top">
                  <span class="score">{{ '%.2f'|format(m.score) }}</span>
                  <span class="mid">{{ m.incident_id }}</span>
                  <span class="loc">{{ m.location or '—' }}{% if m.date %} &middot; {{ m.date }}{% endif %}</span>
                </div>
                <div class="chips">{% for s in m.shared %}<span class="chip">{{ s }}</span>{% endfor %}</div>
                {% if m.photo %}<div class="hint" style="margin-top:6px">reference photo on file: {{ m.photo }}</div>{% endif %}
              </div>
              {% endfor %}
            {% else %}<div class="empty">No records in this area matched the description closely enough.</div>{% endif %}
          </div>
        </div>
        {% endif %}
      {% endif %}
    </section>
  </div>
</div>
</body></html>"""
