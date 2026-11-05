"""Home page: the state of the record at a glance, and the way to each task.

The headline is a sentence built from live counts (reports on record, links
waiting for an analyst), beside a 12-month activity strip. Below it, the
actions (filing a report is the primary one), then the most recent reports
and the strongest links nobody has decided on yet.

Wired into app.py with home_bp.register(app, ...); app.py passes in the
helpers it owns, so this module does not import app.py.
"""
from __future__ import annotations

import re
from datetime import date

from flask import Blueprint, render_template_string

import review_bp
import ui_icons
from linker import store

home_bp = Blueprint("home", __name__)
_HELPERS: dict = {}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def register(app, *, status, marker_of):
    """status() -> dict with sem_ok / ai_ok; marker_of(incident) -> (label, colour)."""
    _HELPERS.update(status=status, marker_of=marker_of)
    app.register_blueprint(home_bp)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def headline(n_reports: int, n_open: int, n_links: int) -> tuple[str, str]:
    """The hero sentence, in two parts (the second is set quieter)."""
    if n_reports == 0:
        return "No reports on record yet.", "File the first one, or load the demo data to try Sirens."
    first = f"{_plural(n_reports, 'report', 'reports')} on record."
    if n_links == 0:
        return first, "No links between them yet."
    if n_open == 0:
        return first, f"All {_plural(n_links, 'link', 'links')} have been reviewed."
    verb = "is" if n_open == 1 else "are"
    return first, f"{_plural(n_open, 'link', 'links')} {verb} waiting for an analyst."


def ago(day: str | None, today: date | None = None) -> str:
    if not day or not _DATE.match(day):
        return "no date"
    d = (today or date.today()) - date.fromisoformat(day)
    days = d.days
    if days < 0:
        return day
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 31:
        return f"{days} days ago"
    if days < 365:
        return f"{days // 30} months ago" if days >= 60 else "a month ago"
    return day


def activity(incidents, today: date | None = None, months: int = 12) -> dict:
    """Reports per month for the last `months` months, oldest first."""
    today = today or date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    keys.reverse()
    counts = {k: 0 for k in keys}
    for i in incidents:
        if i.date and _DATE.match(i.date):
            k = (int(i.date[:4]), int(i.date[5:7]))
            if k in counts:
                counts[k] += 1
    top = max(counts.values()) or 1
    bars = [{"label": f"{_MONTHS[m - 1]} {y}", "n": n, "pct": round(100 * n / top)}
            for (y, m), n in counts.items()]
    return {"bars": bars, "total": sum(counts.values()),
            "first": bars[0]["label"], "last": bars[-1]["label"]}


@home_bp.route("/")
def home_page():
    incidents = store.all_incidents()
    rows = review_bp.build_rows() if incidents else []
    on_tree = [r for r in rows if not r["below"]]
    open_links = [r for r in on_tree if not r["decision"]]
    dated = sorted(incidents, key=lambda i: (i.date or "", i.incident_id), reverse=True)
    recent = []
    for inc in dated[:6]:
        label, colour = _HELPERS["marker_of"](inc)
        snip = (inc.narrative or "").strip().replace("\n", " ")
        recent.append({"id": inc.incident_id, "where": inc.location or "No location",
                       "when": ago(inc.date), "date": inc.date or "", "type": label,
                       "colour": colour, "snip": snip[:140]})
    lead, quiet = headline(len(incidents), len(open_links), len(on_tree))
    latest = recent[0] if recent else None
    return render_template_string(
        _TEMPLATE, lead=lead, quiet=quiet, latest=latest, n_reports=len(incidents),
        n_open=len(open_links), recent=recent, waiting=open_links[:5],
        strip=activity(incidents), status=_HELPERS["status"](), icon=ui_icons.icon)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens</title>
<link rel="stylesheet" href="{{ url_for('static', filename='sirens.css') }}">
</head>
<body>
<div class="bar">
  <a class="brand" href="{{ url_for('home.home_page') }}">Sirens<small>C-IED Incident Link Console</small></a>
  {{ sirens_menu('home') }}
</div>

<main class="wrap">
  <section class="hero" aria-labelledby="state">
    <div>
      <h1 id="state">{{ lead }} <span class="quiet">{{ quiet }}</span></h1>
      {% if latest %}
        <p class="last">Latest report: <span class="mono">{{ latest.id }}</span>, {{ latest.where }}, {{ latest.when }}.</p>
      {% endif %}
      <div class="sys">
        <span class="{{ 'on' if status.sem_ok else '' }}">Meaning match: {{ 'word vectors' if status.sem_ok else 'basic text overlap' }}</span>
        <span class="{{ 'on' if status.ai_ok else '' }}">AI summaries: {{ 'on' if status.ai_ok else 'off' }}</span>
      </div>
      {% if not n_reports %}
        <div class="start">
          <a class="btn" href="{{ url_for('index') }}">File a new report</a>
          <a class="btn ghost" href="{{ url_for('demo.demo_page') }}">Load demo data (fabricated)</a>
        </div>
      {% endif %}
    </div>
    <figure class="strip" aria-labelledby="strip-t" style="margin:0">
      <h2 id="strip-t">Reports per month, last 12 months</h2>
      <div class="bars" role="img" aria-label="{{ strip.total }} reports in the last 12 months">
        {% for b in strip.bars %}<i class="{{ 'zero' if not b.n }}" style="height:{{ [b.pct, 3]|max }}%" title="{{ b.label }}: {{ b.n }}"></i>{% endfor %}
      </div>
      <div class="ends"><span>{{ strip.first }}</span><span>{{ strip.last }}</span></div>
      <table class="sr"><caption>Reports per month</caption>
        {% for b in strip.bars %}<tr><th>{{ b.label }}</th><td>{{ b.n }}</td></tr>{% endfor %}</table>
    </figure>
  </section>

  <nav class="actions" aria-label="Tasks">
    <a class="act primary" href="{{ url_for('index') }}">{{ icon('report') }}
      <div><strong>File a new report</strong><span>Paste the text; Sirens reads it and shows what it links to.</span></div></a>
    <a class="act" href="{{ url_for('brief.brief_page') }}">{{ icon('brief') }}
      <div><strong>Pre-arrival brief</strong><span>What was reported before at a place</span></div></a>
    <a class="act" href="{{ url_for('review.review_page', show='open') }}">{{ icon('review') }}
      <div><strong>Review links</strong><span>Confirm or reject what Sirens found</span></div>
      {% if n_open %}<b class="count num">{{ n_open }}</b>{% endif %}</a>
    <a class="act" href="{{ url_for('incident_map') }}">{{ icon('map') }}
      <div><strong>Map and MGRS</strong><span>Offline street map with grid references</span></div></a>
    <a class="act" href="{{ url_for('dashboard.dashboard_page') }}">{{ icon('dashboard') }}
      <div><strong>Dashboard</strong><span>Counts, networks and data quality</span></div></a>
    <a class="act" href="{{ url_for('munitions.munitions_page') }}">{{ icon('artillery') }}
      <div><strong>Munitions reference</strong><span>Recognise and catalogue by family</span></div></a>
    <a class="act" href="{{ url_for('link_tree') }}">{{ icon('tree') }}
      <div><strong>Link tree</strong><span>Every network as a graph</span></div></a>
  </nav>

  <div class="lists">
    <section class="list" aria-labelledby="recent-t">
      <header><h2 id="recent-t">Recent reports</h2>
        {% if recent %}<a href="{{ url_for('incident_map') }}">See them on the map</a>{% endif %}</header>
      {% if recent %}
      <ol>
        {% for r in recent %}
        <li><a href="{{ url_for('incident_map') }}" title="Map marker: {{ r.type }} (guessed from the text unless filed)">
          <span class="dot" style="background:{{ r.colour }}" aria-hidden="true"></span>
          <span><span class="id">{{ r.id }}</span> <span class="where">{{ r.where }}</span></span>
          <span class="when">{{ r.when }}</span>
          <span class="snip">{{ r.snip }}</span>
        </a></li>
        {% endfor %}
      </ol>
      {% else %}<p class="empty">Reports you file appear here, newest first.</p>{% endif %}
    </section>

    <section class="list" aria-labelledby="wait-t">
      <header><h2 id="wait-t">Links waiting for review</h2>
        {% if waiting %}<a href="{{ url_for('review.review_page', show='open') }}">Review all {{ n_open }}</a>{% endif %}</header>
      {% if waiting %}
      <ol>
        {% for r in waiting %}
        <li><a href="{{ url_for('review.review_page', show='open') }}#{{ r.dom_id }}">
          <span class="band {{ r.band }}">{{ r.band|capitalize }}</span>
          <span><span class="id">{{ r.a }}</span> and <span class="id">{{ r.b }}</span></span>
          <span class="when num">{{ '%.2f'|format(r.score) }}</span>
          <span class="snip">{{ r.reasons[:2]|join('; ') }}</span>
        </a></li>
        {% endfor %}
      </ol>
      {% elif n_reports %}<p class="empty">Nothing waiting. Every link Sirens found has a decision.</p>
      {% else %}<p class="empty">Links appear once there are at least two reports.</p>{% endif %}
    </section>
  </div>
</main>
<footer>Decision support only. Every value traces to the report text, and a person confirms every link.</footer>
</body>
</html>
"""
