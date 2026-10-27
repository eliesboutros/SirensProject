"""Link review: the analyst's Confirm / Reject / Unsure workbench.

A standalone Flask Blueprint (wired into app.py with one line). /review lists
every link the link tree shows (same matcher, same threshold) with its score,
band and the machine's reasons, and lets the analyst record a decision and
notes on each one. Buttons use htmx (served from static/vendor/), so only the
link card being changed is swapped: no page reload.

Analyst decisions live in linker/decisions.py's own append-only tables. The
machine output (scores, reasons, clusters) is never modified, and every
decision can be undone. Decided or annotated links stay listed even if their
score later falls below the threshold, so no decision is ever hidden.
"""
from __future__ import annotations

import re

from flask import Blueprint, abort, render_template_string, request

from linker import decisions, store
from linker.ai import _score_band
from linker.match import Matcher

review_bp = Blueprint("review", __name__)

THRESHOLD = 0.25        # same as /tree, so both pages show the same links
FILTERS = ("all", "open", "confirm", "reject", "unsure")


def _on_tree(link) -> bool:
    """The rule Matcher.all_pairs uses to keep a link."""
    return link.score >= THRESHOLD and bool(link.shared_features or link.shared_entities)


def _dom_id(a: str, b: str) -> str:
    return "lk-" + re.sub(r"[^A-Za-z0-9_-]", "_", f"{a}--{b}")


def _row(link, by_id, decided, notes) -> dict:
    a, b = sorted((link.a, link.b))
    return {
        "a": a, "b": b, "inc_a": by_id[a], "inc_b": by_id[b],
        "dom_id": _dom_id(a, b),
        "score": link.score, "band": _score_band(link.score),
        "reasons": link.reasons,
        "below": not _on_tree(link),
        "decision": decided.get((a, b)),
        "notes": notes.get((a, b), []),
    }


def build_rows() -> list[dict]:
    """Every link on the tree, plus any decided/annotated link that dropped off it."""
    incidents = store.all_incidents()
    by_id = {i.incident_id: i for i in incidents}
    matcher = Matcher().fit(incidents)
    decided = decisions.current_decisions()
    notes = decisions.all_notes()
    links = matcher.all_pairs(incidents, threshold=THRESHOLD)
    seen = {tuple(sorted((l.a, l.b))) for l in links}
    for a, b in sorted((set(decided) | set(notes)) - seen):
        if a in by_id and b in by_id:
            links.append(matcher.score(by_id[a], by_id[b]))
    rows = [_row(l, by_id, decided, notes) for l in links]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def _one_row(a: str, b: str) -> dict:
    incidents = store.all_incidents()
    by_id = {i.incident_id: i for i in incidents}
    if a not in by_id or b not in by_id:
        abort(404, "unknown incident id")
    link = Matcher().fit(incidents).score(by_id[a], by_id[b])
    a, b = sorted((a, b))
    return _row(link, by_id,
                {(a, b): decisions.current_decision(a, b)},
                {(a, b): decisions.notes_for(a, b)})


def _tally() -> dict:
    counts = {d: 0 for d in decisions.DECISIONS}
    for d in decisions.current_decisions().values():
        counts[d] = counts.get(d, 0) + 1
    return counts


@review_bp.route("/review")
def review_page():
    show = request.args.get("show", "all")
    if show not in FILTERS:
        show = "all"
    rows = build_rows()
    if show == "open":
        shown = [r for r in rows if not r["decision"]]
    elif show != "all":
        shown = [r for r in rows if r["decision"] == show]
    else:
        shown = rows
    return render_template_string(_CARD + _PAGE, rows=shown, total=len(rows),
                                  show=show, filters=FILTERS, tally=_tally(),
                                  db_count=store.count())


@review_bp.route("/review/decide", methods=["POST"])
def decide():
    a, b = request.form.get("a", ""), request.form.get("b", "")
    decision = request.form.get("decision", "")
    analyst = request.form.get("analyst", "")[:40]
    if decision == "undo":
        _one_row(a, b)                         # 404 on unknown ids
        decisions.clear_decision(a, b, analyst=analyst)
    else:
        try:
            _one_row(a, b)
            decisions.set_decision(a, b, decision, analyst=analyst)
        except ValueError as e:
            return str(e), 400
    return _fragment(a, b)


@review_bp.route("/review/note", methods=["POST"])
def note():
    a, b = request.form.get("a", ""), request.form.get("b", "")
    try:
        _one_row(a, b)
        decisions.add_note(a, b, request.form.get("note", "")[:2000],
                           analyst=request.form.get("analyst", "")[:40])
    except ValueError as e:
        return str(e), 400
    return _fragment(a, b)


def _fragment(a, b):
    """The refreshed link card, plus the decision tally swapped out-of-band."""
    return render_template_string(_CARD + "{{ card(r) }}" + _TALLY_OOB,
                                  r=_one_row(a, b), tally=_tally())


_CARD = r"""{% import "forms_ui.html" as f %}{% macro card(r) %}
<article class="link{% if r.decision %} is-{{ r.decision }}{% endif %}" id="{{ r.dom_id }}">
  <div class="top">
    <span class="pair mono">{{ r.a }} &harr; {{ r.b }}</span>
    <span class="score">{{ '%.2f'|format(r.score) }}</span>
    <span class="band band-{{ r.band }}">{{ r.band }}</span>
    {% if r.below %}<span class="below">below link threshold now</span>{% endif %}
    <span class="verdict">
      {% if r.decision %}Analyst: <strong>{{ {'confirm':'Confirmed','reject':'Rejected','unsure':'Unsure'}[r.decision] }}</strong>
      {% else %}No analyst decision yet{% endif %}
    </span>
  </div>
  <div class="incs">
    <div><span class="mono">{{ r.a }}</span> &middot; {{ r.inc_a.location or 'no location' }} &middot; {{ r.inc_a.date or 'no date' }}</div>
    <div><span class="mono">{{ r.b }}</span> &middot; {{ r.inc_b.location or 'no location' }} &middot; {{ r.inc_b.date or 'no date' }}</div>
  </div>
  <div class="why">
    <div class="subhead">Why the machine linked them</div>
    {% if r.reasons %}<ul>{% for x in r.reasons %}<li>{{ x }}</li>{% endfor %}</ul>
    {% else %}<p class="weak">No shared evidence at the current score.</p>{% endif %}
  </div>
  <div class="actions">
    {% for d, label in [('confirm','Confirm'),('reject','Reject'),('unsure','Unsure')] %}
    <button type="button" class="dbtn d-{{ d }}{% if r.decision == d %} on{% endif %}"
      hx-post="{{ url_for('review.decide') }}" hx-include="#analyst"
      hx-vals='{{ {"a": r.a, "b": r.b, "decision": d}|tojson }}'
      hx-target="#{{ r.dom_id }}" hx-swap="outerHTML">{{ label }}</button>
    {% endfor %}
    {% if r.decision %}
    <button type="button" class="dbtn undo"
      hx-post="{{ url_for('review.decide') }}" hx-include="#analyst"
      hx-vals='{{ {"a": r.a, "b": r.b, "decision": "undo"}|tojson }}'
      hx-target="#{{ r.dom_id }}" hx-swap="outerHTML">Undo</button>
    {% endif %}
  </div>
  <div class="notes">
    {% for n in r.notes %}
    <div class="note"><span class="meta">{{ n.created_at.replace('T', ' ')[:16] }}{% if n.analyst %} &middot; {{ n.analyst }}{% endif %}</span> {{ n.note }}</div>
    {% endfor %}
    <form class="f-form f-inline" novalidate hx-post="{{ url_for('review.note') }}" hx-include="#analyst"
          hx-target="#{{ r.dom_id }}" hx-swap="outerHTML">
      <input type="hidden" name="a" value="{{ r.a }}"><input type="hidden" name="b" value="{{ r.b }}">
      {{ f.input("note", "Add a note", "note", id="note-" ~ r.dom_id, placeholder="e.g. dates two months apart",
                 rules="required", required_msg="Write a note before adding it.", extra='maxlength="2000"') }}
      <button type="submit" class="f-btn ghost small" data-busy-text="Saving…">Add note</button>
    </form>
  </div>
</article>
{% endmacro %}"""

_TALLY_OOB = r"""
<span id="tally" hx-swap-oob="true">Confirmed {{ tally.confirm }} &middot; Rejected {{ tally.reject }} &middot; Unsure {{ tally.unsure }}</span>"""

_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens — Link review</title>
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
       line-height:1.5;-webkit-font-smoothing:antialiased}
  a{color:var(--link)}
  .bar{display:flex;align-items:center;gap:20px;flex-wrap:wrap;
       padding:18px 32px;background:var(--ink);color:#eef2f5;
       border-bottom:3px solid var(--sig)}
  .brand{font-family:var(--mono);font-weight:600;letter-spacing:.16em;
         text-transform:uppercase;font-size:15px}
  .brand small{display:block;letter-spacing:.06em;font-size:10px;color:#9fb0bd;
               font-weight:400;margin-top:2px}
  .wrap{max-width:1180px;margin:0 auto;padding:36px 48px 90px}
  @media(max-width:1000px){.wrap{padding:24px 18px 60px}}
  .mono{font-family:var(--mono)}
  .weak{color:var(--weak)}
  .head{display:flex;flex-wrap:wrap;gap:14px 26px;align-items:center;margin-bottom:10px}
  .head h1{font-size:20px;margin:0;font-weight:600}
  .stat{font-family:var(--mono);font-size:12.5px;color:var(--ink-soft)}
  .lead{font-size:13.5px;color:var(--ink-soft);background:var(--line-2);border-radius:4px;
        padding:10px 14px;margin:0 0 18px}
  .link{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--line);
        border-radius:7px;padding:16px 20px;margin-bottom:14px;
        box-shadow:0 1px 2px rgba(22,32,43,.04),0 4px 14px rgba(22,32,43,.04)}
  .link.is-confirm{border-left-color:#5b8a63}
  .link.is-reject{border-left-color:#b0605a}
  .link.is-unsure{border-left-color:var(--sig)}
  .top{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
  .pair{font-weight:600;font-size:14px}
  .score{font-family:var(--mono);font-weight:700;font-size:12.5px;padding:2px 8px;
         border-radius:3px;background:var(--sig-soft);color:#7a4e12}
  .band{font-family:var(--mono);font-size:11px;padding:2px 7px;border-radius:3px;border:1px solid var(--line)}
  .band-strong{background:#e7efe5;color:#3d6b45}
  .band-medium{background:#f3ecdf;color:#7a4e12}
  .band-weak{background:#eef0ee;color:var(--weak)}
  .below{font-size:11.5px;color:var(--weak);font-style:italic}
  .verdict{margin-left:auto;font-size:13px;color:var(--ink-soft)}
  .incs{display:flex;flex-wrap:wrap;gap:4px 28px;font-size:13px;color:var(--ink-soft);margin:8px 0 4px}
  .subhead{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--weak);
           font-family:var(--mono);margin:10px 0 4px}
  .why ul{margin:0;padding-left:18px;font-size:13.5px}
  .actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 6px}
  .dbtn{font-family:var(--sans);font-size:13px;font-weight:600;padding:6px 13px;border-radius:4px;
        border:1px solid var(--line);background:#fff;color:var(--ink);cursor:pointer}
  .dbtn:hover{border-color:var(--ink-soft)}
  .d-confirm.on{background:#5b8a63;border-color:#5b8a63;color:#fff}
  .d-reject.on{background:#b0605a;border-color:#b0605a;color:#fff}
  .d-unsure.on{background:var(--sig);border-color:var(--sig);color:#fff}
  .undo{color:var(--weak);font-weight:500}
  .notes{border-top:1px solid var(--line-2);margin-top:10px;padding-top:10px}
  .note{font-size:13px;margin-bottom:6px}
  .note .meta{font-family:var(--mono);font-size:11px;color:var(--weak);margin-right:6px}
  .notes form{margin-top:6px}
  .htmx-request{opacity:.6}
  #flash{display:none;background:#fbeceb;border:1px solid #e7b7b2;color:#a4332b;
         padding:9px 13px;border-radius:4px;font-size:13px;margin-bottom:14px}
  .empty{color:var(--weak);padding:20px 2px}
</style>
{{ f.assets() }}
</head>
<body>
<div class="bar">
  <div class="brand">Sirens<small>link review · analyst decisions</small></div>
  {{ sirens_menu('review') }}
</div>
<div class="wrap">
  <div class="head">
    <h1>Link review</h1>
    <span class="stat">{{ total }} links &middot; <span id="tally">Confirmed {{ tally.confirm }} &middot; Rejected {{ tally.reject }} &middot; Unsure {{ tally.unsure }}</span></span>
  </div>
  <p class="lead">Every link is a lead for a human analyst, never a conclusion. Your decisions and
    notes are stored separately from the machine's scores, which are never changed, and every
    decision can be undone. Links shown: score {{ '%.2f'|format(0.25) }} or more with shared evidence
    (the same set as the link tree).</p>
  <div id="flash"></div>
  {% set names = {'all':'all','open':'no decision','confirm':'confirmed','reject':'rejected','unsure':'unsure'} %}
  <form class="f-form f-filterbar" onsubmit="return false" aria-label="Review filters">
    <div class="f-field">
      <div class="f-labelrow"><span class="f-label">Show links</span></div>
      <nav class="f-seg filters" aria-label="Filter by decision">
        {% for flt in filters %}<a href="{{ url_for('review.review_page', show=flt) }}" class="{{ 'on' if flt == show else '' }}"{% if flt == show %} aria-current="true"{% endif %}>{{ names[flt] }}</a>{% endfor %}
      </nav>
    </div>
    {{ f.input("analyst", "Analyst initials", "analyst", placeholder="e.g. BE", optional=True, extra='maxlength="40"') }}
  </form>
  {{ f.chips([] if show == 'all' else [("Decision: " ~ names[show], url_for('review.review_page'))], url_for('review.review_page')) }}

  {% if db_count == 0 %}
    <p class="empty">No incidents on record yet. <a href="{{ url_for('demo.demo_page') }}">Load the demo data</a> first.</p>
  {% elif not rows %}
    <p class="empty">No links match this filter.</p>
  {% endif %}
  {% for r in rows %}{{ card(r) }}{% endfor %}
</div>

<script src="{{ url_for('static', filename='vendor/htmx.min.js') }}"></script>
<script>
  // Remember the analyst's initials on this machine only.
  var an = document.getElementById('analyst');
  an.value = localStorage.getItem('sirens-analyst') || '';
  an.addEventListener('change', function(){ localStorage.setItem('sirens-analyst', an.value); });
  // Show server-side refusals (e.g. an empty note) instead of failing silently.
  document.body.addEventListener('htmx:responseError', function(e){
    var f = document.getElementById('flash');
    f.textContent = 'Not saved: ' + (e.detail.xhr.responseText || e.detail.xhr.status);
    f.style.display = 'block';
  });
  document.body.addEventListener('htmx:afterSwap', function(){
    document.getElementById('flash').style.display = 'none';
  });
</script>
</body>
</html>
"""
