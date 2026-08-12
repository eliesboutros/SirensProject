#!/usr/bin/env python3
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
import webbrowser
from threading import Timer

from flask import Flask, redirect, render_template_string, request, url_for

from linker.ingest import load_incidents
from linker.extract import FeatureExtractor
from linker.match import Matcher
from linker import store, semantic, ai
from linker.models import Incident

ROOT = pathlib.Path(__file__).resolve().parent
TAXONOMY = ROOT / "data" / "taxonomy" / "cied_lexicon.json"
SAMPLES = ROOT / "data" / "sample_incidents"

app = Flask(__name__)

# Load the extractor once (spaCy start-up cost paid a single time).
_EXTRACTOR = FeatureExtractor(TAXONOMY, use_ner=True)


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
    )


@app.route("/analyse", methods=["POST"])
def analyse():
    f = request.form
    narrative = (f.get("narrative") or "").strip()
    inc = Incident(
        incident_id=(f.get("incident_id") or store.next_incident_id()).strip(),
        date=(f.get("date") or None),
        location=(f.get("location") or None),
        narrative=narrative,
        photo=(f.get("photo") or None),
    )
    if not narrative:
        return render_template_string(
            TEMPLATE, result=None, form=f, status=_status(),
            suggested_id=inc.incident_id,
            error="Paste a report narrative first — that's what Sirens reads.")

    _EXTRACTOR.extract(inc)
    save = f.get("action") == "save"
    if save:
        store.add_incident(inc)

    result = _analyse(inc, run_llm=(f.get("use_ai") == "on"))
    result["incident"] = inc
    result["saved"] = save
    return render_template_string(
        TEMPLATE, result=result, form=f, status=_status(),
        suggested_id=store.next_incident_id(), error=None)


@app.route("/seed", methods=["POST"])
def seed():
    incidents = load_incidents(SAMPLES)
    _EXTRACTOR.extract_all(incidents)
    store.add_incidents(incidents)
    return redirect(url_for("index"))


@app.route("/clear", methods=["POST"])
def clear():
    store.clear()
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


TEMPLATE = r"""<!doctype html>
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
       line-height:1.5;-webkit-font-smoothing:antialiased}
  a{color:var(--link)}
  .bar{display:flex;align-items:center;gap:18px;flex-wrap:wrap;
       padding:14px 26px;background:var(--ink);color:#eef2f5;
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
  .wrap{max-width:1180px;margin:0 auto;padding:26px 22px 60px}
  .grid{display:grid;grid-template-columns:minmax(0,420px) minmax(0,1fr);gap:22px;align-items:start}
  @media(max-width:840px){.grid{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:6px}
  .card h2{margin:0;padding:14px 18px;border-bottom:1px solid var(--line-2);
           font-size:12px;letter-spacing:.14em;text-transform:uppercase;
           color:var(--ink-soft);font-family:var(--mono);font-weight:600}
  .card .body{padding:18px}
  label{display:block;font-size:12px;letter-spacing:.03em;color:var(--ink-soft);
        margin:0 0 5px;font-weight:600}
  input[type=text],textarea{width:100%;padding:9px 11px;border:1px solid var(--line);
        border-radius:4px;font-family:var(--sans);font-size:14px;color:var(--ink);
        background:#fcfdfc}
  input[type=text]:focus,textarea:focus{outline:2px solid var(--link);
        outline-offset:1px;border-color:var(--link)}
  textarea{min-height:190px;resize:vertical;line-height:1.55}
  .row{display:flex;gap:12px}.row>div{flex:1;min-width:0}
  .field{margin-bottom:14px}
  .mono{font-family:var(--mono)}
  .hint{font-size:12px;color:var(--weak);margin-top:5px}
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
</head>
<body>
<div class="bar">
  <div class="brand">Sirens<small>C-IED Incident Link Console</small></div>
  <div class="badges">
    <span class="badge {{ 'on' if status.db_count else 'off' }}"><span class="dot"></span>{{ status.db_count }} in database</span>
    <span class="badge {{ 'on' if status.sem_ok else 'off' }}"><span class="dot"></span>meaning: {{ 'vectors' if status.sem_ok else 'lexical' }}</span>
    <span class="badge {{ 'on' if status.ai_ok else 'off' }}"><span class="dot"></span>AI: {{ 'ready' if status.ai_ok else 'off' }}</span>
  </div>
</div>

<div class="wrap">
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<div class="grid">

  <!-- LEFT: input -->
  <section class="card">
    <h2>New report</h2>
    <div class="body">
      <form method="post" action="/analyse">
        <div class="row">
          <div class="field">
            <label for="incident_id">Incident ID</label>
            <input type="text" id="incident_id" name="incident_id" class="mono"
                   value="{{ form.incident_id or suggested_id }}">
          </div>
          <div class="field">
            <label for="date">Date</label>
            <input type="text" id="date" name="date" placeholder="2026-03-04"
                   value="{{ form.date or '' }}">
          </div>
        </div>
        <div class="field">
          <label for="location">Location</label>
          <input type="text" id="location" name="location"
                 placeholder="Route Copper, Al-Fakir District" value="{{ form.location or '' }}">
        </div>
        <div class="field">
          <label for="narrative">Report narrative</label>
          <textarea id="narrative" name="narrative"
            placeholder="Paste the incident report here. Sirens reads the free text and pulls out the device signature, names, groups and numbers.">{{ form.narrative or '' }}</textarea>
          <div class="hint">Free text is fine — messy field reporting is what it's built for.</div>
        </div>
        <div class="field">
          <label for="photo">Photo reference <span style="font-weight:400;color:var(--weak)">(optional, filed not analysed)</span></label>
          <input type="text" id="photo" name="photo" placeholder="img_014.jpg" value="{{ form.photo or '' }}">
        </div>
        <div class="actions">
          <button class="btn" type="submit" name="action" value="analyse">Analyse</button>
          <button class="btn ghost" type="submit" name="action" value="save">Save to database</button>
          <label class="toggle {{ '' if status.ai_ok else 'disabled' }}">
            <input type="checkbox" name="use_ai" {{ 'checked' if status.ai_ok else 'disabled' }}>
            AI assessment
          </label>
        </div>
        {% if not status.ai_ok %}
          <div class="hint">AI assessment is off — {{ status.ai_reason }}</div>
        {% endif %}
      </form>
    </div>
  </section>

  <!-- RIGHT: results -->
  <section>
  {% if not result %}
    <div class="card"><div class="body">
      {% if status.db_count == 0 %}
        <p class="empty">The database is empty. Load the 13 sample incidents to try it, then paste a new report to see what it links to.</p>
        <form method="post" action="/seed"><button class="btn" type="submit">Load sample incidents</button></form>
      {% else %}
        <p class="empty">Paste a report on the left and press <strong>Analyse</strong>. Sirens checks it against the {{ status.db_count }} incidents on record — by shared signature and by meaning — and, with AI on, explains the strongest links.</p>
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
      </div>
    </div>

    {% if result.assessment %}
      <div class="ai result-card">
        <h3>AI linkage assessment
          {% if result.assessment.ok %}<span class="tag">{{ result.assessment.model }}</span>{% endif %}</h3>
        {% if result.assessment.ok %}
          <div class="txt">{{ result.assessment.text }}</div>
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
          </div>
          {% endfor %}
        {% else %}<div class="empty">Nothing to compare against yet — save a few incidents first.</div>{% endif %}
      </div>
    </div>
  {% endif %}
  </section>
</div>
</div>
<footer>Decision-support for incident link analysis — every value traces to source text; a human analyst confirms any link. Photos are filed, never analysed.</footer>
</body>
</html>"""


def _open():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    store.connect()  # ensure the DB file exists on first run
    Timer(1.2, _open).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
