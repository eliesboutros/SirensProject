"""Dashboard: statistics and charts over the incidents on record.

A standalone Flask Blueprint (wired into app.py with one line). Sections:
overview tiles, time and place, signatures, candidate networks, link strength
and analyst review, and data quality. One filter row (date range, area,
initiation method, signature feature) scopes every tile, chart and table
on the page. Charts use the vendored Chart.js (static/vendor/), so the page
works with no network. Every chart has a table twin with the exact numbers.

Counts only: the page describes what is on record, it draws no conclusions.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from flask import Blueprint, render_template_string, request, url_for

from linker import decisions, stats, store
from linker.match import Matcher

dashboard_bp = Blueprint("dashboard", __name__)

THRESHOLD = 0.25          # same link threshold as /tree and /review
TOP_AREAS = 10            # more areas than this fold into "Other"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _label(value: str) -> str:
    return value.replace("_", " ")


def _initiations(inc) -> set[str]:
    return {v for (k, v) in inc.feature_keys() if k == "initiation"}


def read_filters(args, incidents) -> dict:
    """Validated filters; anything malformed is ignored rather than erroring."""
    areas = sorted({i.location for i in incidents if i.location})
    inits = sorted({v for i in incidents for (k, v) in i.feature_keys() if k == "initiation"})
    features = {f"{k}:{v}" for i in incidents for (k, v) in i.feature_keys() if k in stats.FACETS}
    feature_opts = [(stats.FACET_LABELS[f], [(fv, stats.label(fv.split(":", 1)[1]))
                     for fv in sorted(x for x in features if x.startswith(f + ":"))])
                    for f in stats.FACETS]
    f = {
        "start": args.get("from", "") if _DATE.match(args.get("from", "")) else "",
        "end": args.get("to", "") if _DATE.match(args.get("to", "")) else "",
        "area": args.get("area", "") if args.get("area", "") in areas else "",
        "initiation": args.get("initiation", "") if args.get("initiation", "") in inits else "",
        "feature": args.get("feature", "") if args.get("feature", "") in features else "",
    }
    return f | {"areas": areas, "inits": inits, "init_opts": [(v, _label(v)) for v in inits],
                "feature_opts": [g for g in feature_opts if g[1]]}


def apply_filters(incidents, f) -> list:
    out = []
    for i in incidents:
        if (f["start"] or f["end"]) and not i.date:
            continue                       # undated reports can't sit in a date range
        if f["start"] and (i.date or "") < f["start"]:
            continue
        if f["end"] and (i.date or "") > f["end"]:
            continue
        if f["area"] and i.location != f["area"]:
            continue
        if f["initiation"] and f["initiation"] not in _initiations(i):
            continue
        if f["feature"] and tuple(f["feature"].split(":", 1)) not in i.feature_keys():
            continue
        out.append(i)
    return out


def timeline(incidents) -> dict:
    """Incidents per month, every month between the first and last present (zeros kept)."""
    months = Counter(i.date[:7] for i in incidents if i.date and _DATE.match(i.date))
    labels, values = [], []
    if months:
        y, m = map(int, min(months).split("-"))
        y_end, m_end = map(int, max(months).split("-"))
        while (y, m) <= (y_end, m_end):
            labels.append(f"{_MONTHS[m - 1]} {y}")
            values.append(months.get(f"{y:04d}-{m:02d}", 0))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    undated = sum(1 for i in incidents if not (i.date and _DATE.match(i.date)))
    return {"labels": labels, "values": values, "undated": undated}


def by_area(incidents) -> dict:
    counts = sorted(Counter(i.location or "no location" for i in incidents).items(),
                    key=lambda kv: (-kv[1], kv[0]))
    top, rest = counts[:TOP_AREAS], counts[TOP_AREAS:]
    labels = [a for a, _ in top]
    values = [n for _, n in top]
    if rest:
        labels.append(f"Other ({len(rest)} areas)")
        values.append(sum(n for _, n in rest))
    return {"labels": labels, "values": values, "keys": [a for a, _ in top]}


def by_initiation(incidents) -> dict:
    """An incident reporting two methods counts under both, matching the filter."""
    counts = sorted(Counter(v for i in incidents for v in _initiations(i)).items(),
                    key=lambda kv: (-kv[1], kv[0]))      # ties: A-Z, stable across runs
    missing = sum(1 for i in incidents if not _initiations(i))
    labels = [_label(k) for k, _ in counts] + (["not recorded"] if missing else [])
    values = [n for _, n in counts] + ([missing] if missing else [])
    multi = sum(1 for i in incidents if len(_initiations(i)) > 1)
    return {"labels": labels, "values": values, "keys": [k for k, _ in counts], "multi": multi}


def active_chips(f) -> list[tuple[str, str]]:
    """One (label, remove-url) per active filter; each URL keeps the other filters."""
    params = {"from": f["start"], "to": f["end"], "area": f["area"],
              "initiation": f["initiation"], "feature": f["feature"]}
    params = {k: v for k, v in params.items() if v}

    def describe(k, v):
        if k == "from":
            return f"From {v}"
        if k == "to":
            return f"To {v}"
        if k == "area":
            return f"Area: {v}"
        if k == "initiation":
            return f"Method: {_label(v)}"
        facet, value = v.split(":", 1)
        return f"{stats.FACET_LABELS.get(facet, facet)}: {_label(value)}"

    return [(describe(k, v), url_for("dashboard.dashboard_page", **{o: w for o, w in params.items() if o != k}))
            for k, v in params.items()]


def link_stats(view_links, current) -> dict:
    """Links whose two incidents are both in view, and how many an analyst confirmed."""
    pairs = {tuple(sorted((l.a, l.b))) for l in view_links}
    confirmed = sum(1 for p, d in current.items() if d == "confirm" and p in pairs)
    return {"links": len(pairs), "confirmed": confirmed}


@dashboard_bp.route("/dashboard")
def dashboard_page():
    incidents = store.all_incidents()
    f = read_filters(request.args, incidents)
    shown = apply_filters(incidents, f)
    active = any(f[k] for k in ("start", "end", "area", "initiation", "feature"))
    # Score every pair once (rarity weights fitted on the full record, as on /tree).
    links = Matcher().fit(incidents).all_pairs(incidents, threshold=THRESHOLD) if incidents else []
    view_links = stats.links_in_view(links, shown)
    current = decisions.current_decisions()
    nets = stats.networks(incidents, links, shown)
    strength = stats.link_strength(view_links, current)
    sig = stats.signatures(shown)
    return render_template_string(
        _TEMPLATE, f=f, active=active, total=len(incidents), shown=shown,
        n_areas=len({i.location for i in shown if i.location}),
        stats=link_stats(view_links, current), nets=nets, strength=strength,
        sig=sig, qual=stats.quality(shown), active_chips=active_chips(f),
        charts={"timeline": timeline(shown), "area": by_area(shown),
                "initiation": by_initiation(shown), "signatures": sig,
                "networks": {"labels": nets["labels"], "values": nets["values"]},
                "hist": {"labels": strength["hist_labels"], "values": strength["hist_values"]}},
        label=_label, today=date.today().isoformat())


_TEMPLATE = r"""{% import "forms_ui.html" as fm %}<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens — Dashboard</title>
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
  .wrap{max-width:1400px;margin:0 auto;padding:32px 48px 90px}
  @media(max-width:1000px){.wrap{padding:22px 18px 60px}}
  h1{font-size:20px;font-weight:600;margin:0 0 14px}
  .scope{font-size:13px;color:var(--ink-soft);margin:4px 0 20px}
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:22px}
  .tile{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:16px 20px;
        box-shadow:0 1px 2px rgba(22,32,43,.04),0 4px 16px rgba(22,32,43,.05)}
  .tile .k{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--weak);font-family:var(--mono)}
  .tile .v{font-size:30px;font-weight:600;margin-top:4px}
  .tile .s{font-size:12px;color:var(--weak)}
  .grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px}
  @media(max-width:1000px){.grid{grid-template-columns:minmax(0,1fr)}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:9px;
        box-shadow:0 1px 2px rgba(22,32,43,.04),0 4px 16px rgba(22,32,43,.05)}
  .card.wide{grid-column:1/-1}
  .card h2{margin:0;padding:14px 20px;border-bottom:1px solid var(--line-2);
           font-size:12px;letter-spacing:.14em;text-transform:uppercase;
           color:var(--ink-soft);font-family:var(--mono);font-weight:600}
  .card .body{padding:18px 20px 16px;overflow-x:auto}   /* wide tables scroll inside their card on phones */
  .plot{position:relative;height:260px}
  .plot.tall{height:320px}
  .hint{font-size:12px;color:var(--weak);margin-top:8px}
  details{margin-top:10px;font-size:13px}
  summary{cursor:pointer;color:var(--link)}
  table{border-collapse:collapse;margin-top:8px;font-variant-numeric:tabular-nums;font-size:13.5px}
  th,td{text-align:left;padding:4px 18px 4px 0;border-bottom:1px solid var(--line-2)}
  th{font-size:12px;font-weight:600;color:var(--ink-soft)}
  .nowrap{white-space:nowrap}
  td.n{text-align:right}
  .empty{color:var(--weak);padding:20px 2px}
  .jump{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 22px}
  .jump a{font-family:var(--mono);font-size:12px;text-decoration:none;color:var(--ink-soft);background:#fff;
        border:1px solid var(--line);border-radius:3px;padding:5px 11px}
  .jump a:hover{border-color:var(--ink-soft)}
  h2.sec{font-size:15px;font-weight:600;margin:34px 0 4px}
  p.lede{font-size:13px;color:var(--weak);margin:0 0 14px}
  .cardtools{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
  .cardtools select{padding:6px 9px;border:1px solid var(--line);border-radius:4px;font-family:var(--sans);
        font-size:13.5px;background:#fcfdfc;color:var(--ink)}
  .chips{display:flex;flex-wrap:wrap;gap:4px}
  .chip{font-family:var(--mono);font-size:11px;padding:2px 7px;border-radius:3px;background:var(--sig-soft);
        color:#7a4e12;border:1px solid #e6d3b0;white-space:nowrap}
  .band{font-family:var(--mono);font-size:11px;padding:1px 6px;border-radius:3px;border:1px solid var(--line)}
  .band-strong{background:#e7efe5;color:#3d6b45}.band-medium{background:#f3ecdf;color:#7a4e12}.band-weak{background:#eef0ee;color:var(--weak)}
  table.wide{width:100%}
  table.wide td{vertical-align:top;padding-top:7px;padding-bottom:7px}
  .meters{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px 34px}
  .mrow .top{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px}
  .mrow .top b{font-weight:600}
  .mrow .top span{color:var(--weak);font-variant-numeric:tabular-nums}
  .meter{height:8px;background:var(--line-2);border-radius:4px;overflow:hidden}
  .meter span{display:block;height:100%;background:var(--sig);border-radius:4px}
  .missing{font-size:12px;color:var(--ink-soft)}
  .mono{font-family:var(--mono)}
</style>
{{ fm.assets() }}
</head>
<body>
<div class="bar">
  <div class="brand">Sirens<small>dashboard · incidents on record</small></div>
  {{ sirens_menu('dashboard') }}
</div>
<div class="wrap">
  <h1>Dashboard</h1>
  <form class="f-form f-filterbar" method="get" action="{{ url_for('dashboard.dashboard_page') }}" novalidate aria-label="Dashboard filters">
    {{ fm.input("from", "From", "from", type="date", value=f.start, optional=True, extra='max="' ~ today ~ '"') }}
    {{ fm.input("to", "To", "to", type="date", value=f.end, optional=True, extra='max="' ~ today ~ '"') }}
    {{ fm.select("area", "Area", "area", f.areas, selected=f.area, blank="all areas", optional=True) }}
    {{ fm.select("initiation", "Initiation method", "initiation", f.init_opts, selected=f.initiation, blank="all methods", optional=True) }}
    <div class="f-field">
      {{ fm.label("feature", "Signature feature", "feature", optional=True) }}
      <select class="f-input" id="feature" name="feature" aria-describedby="e-feature">
        <option value="">any feature</option>
        {% for group, opts in f.feature_opts %}<optgroup label="{{ group }}">
          {% for v, l in opts %}<option value="{{ v }}" {{ 'selected' if v == f.feature else '' }}>{{ l }}</option>{% endfor %}
        </optgroup>{% endfor %}
      </select>
      <div class="f-error" id="e-feature" aria-live="polite"></div>
    </div>
    <div class="f-actions"><button class="f-btn" type="submit" data-busy-text="Applying…">Apply</button></div>
  </form>
  {{ fm.chips(active_chips, url_for('dashboard.dashboard_page')) }}
  <p class="scope">{% if active %}Showing {{ shown|length }} of {{ total }} incidents matching the filters.{% else %}Showing all {{ total }} incidents on record.{% endif %}
    Counts describe the record only; every link is a lead for an analyst, not a conclusion.</p>

  {% if total == 0 %}
    <p class="empty">No incidents on record yet. <a href="{{ url_for('demo.demo_page') }}">Load the demo data</a> first.</p>
  {% else %}
  <nav class="jump" aria-label="Dashboard sections">
    <a href="#overview">Overview</a><a href="#time">Time and place</a><a href="#signatures">Signatures</a>
    <a href="#networks">Networks</a><a href="#links">Links and review</a><a href="#quality">Data quality</a>
  </nav>
  <div class="tiles" id="overview">
    <div class="tile"><div class="k">Incidents</div><div class="v">{{ shown|length }}</div><div class="s">in view</div></div>
    <div class="tile"><div class="k">Areas</div><div class="v">{{ n_areas }}</div><div class="s">with at least one incident</div></div>
    <div class="tile"><div class="k">Links</div><div class="v">{{ stats.links }}</div><div class="s">between incidents in view (score &ge; 0.25)</div></div>
    <div class="tile"><div class="k">Confirmed</div><div class="v">{{ stats.confirmed }}</div><div class="s">of those links, by an analyst (<a href="{{ url_for('review.review_page') }}">review</a>)</div></div>
  </div>

  {% if not shown %}
    <p class="empty">No incidents match these filters. <a href="{{ url_for('dashboard.dashboard_page') }}">Reset</a></p>
  {% else %}
  <h2 class="sec" id="time">Time and place</h2>
  <p class="lede">When and where incidents in view were reported.</p>
  <div class="grid">
    <section class="card wide"><h2>Incidents per month</h2><div class="body">
      <div class="plot"><canvas id="c-timeline" role="img" aria-label="Bar chart of incidents per month"></canvas></div>
      {% if charts.timeline.undated %}<p class="hint">{{ charts.timeline.undated }} incident(s) without a date are not on the timeline.</p>{% endif %}
      <details><summary>Show table</summary><table><tr><th>Month</th><th>Incidents</th></tr>
        {% for l in charts.timeline.labels %}<tr><td>{{ l }}</td><td class="n">{{ charts.timeline['values'][loop.index0] }}</td></tr>{% endfor %}
      </table></details>
    </div></section>

    <section class="card"><h2>Incidents by area</h2><div class="body">
      <div class="plot tall"><canvas id="c-area" role="img" aria-label="Bar chart of incidents by area"></canvas></div>
      <p class="hint">Click a bar to filter by that area. The grey bar groups the smaller areas.</p>
      <details><summary>Show table</summary><table><tr><th>Area</th><th>Incidents</th></tr>
        {% for l in charts.area.labels %}<tr><td>{{ l }}</td><td class="n">{{ charts.area['values'][loop.index0] }}</td></tr>{% endfor %}
      </table></details>
    </div></section>

    <section class="card"><h2>Initiation method</h2><div class="body">
      <div class="plot tall"><canvas id="c-init" role="img" aria-label="Bar chart of incidents by initiation method"></canvas></div>
      <p class="hint">Click a bar to filter by that method.{% if charts.initiation.multi %}
        {{ charts.initiation.multi }} incident(s) report more than one method and count under each.{% endif %}</p>
      <details><summary>Show table</summary><table><tr><th>Initiation method</th><th>Incidents</th></tr>
        {% for l in charts.initiation.labels %}<tr><td>{{ l }}</td><td class="n">{{ charts.initiation['values'][loop.index0] }}</td></tr>{% endfor %}
      </table></details>
    </div></section>
  </div>

  <h2 class="sec" id="signatures">Signatures</h2>
  <p class="lede">Which descriptive features the reports in view mention most. An incident can report more than one value.</p>
  <div class="grid">
    <section class="card wide"><h2>Signature breakdown</h2><div class="body">
      <div class="cardtools f-form">{{ fm.label("facet", "Feature", "facet") }}
        <select id="facet">{% for k, v in sig.items() %}<option value="{{ k }}" {{ 'selected' if loop.first else '' }}>{{ v.name }}</option>{% endfor %}</select>
      </div>
      <div class="plot tall"><canvas id="c-sig" role="img" aria-label="Bar chart of the selected signature feature"></canvas></div>
      <p class="hint">Click a bar to filter the whole page by that feature. The grey bar counts reports where the feature was not recorded.</p>
      <details><summary>Show table</summary>
        {% for k, v in sig.items() %}<table class="sig-table" data-facet="{{ k }}"{% if not loop.first %} hidden{% endif %}>
          <tr><th>{{ v.name }}</th><th>Incidents</th></tr>
          {% for l in v.labels %}<tr><td>{{ l }}</td><td class="n">{{ v['values'][loop.index0] }}</td></tr>{% endfor %}
        </table>{% endfor %}
      </details>
    </div></section>
  </div>

  <h2 class="sec" id="networks">Networks</h2>
  <p class="lede">Candidate networks from the same clustering as the <a href="{{ url_for('link_tree') }}">link tree</a>,
    listed when at least one member is in view. A candidate network is a lead, not a finding.</p>
  {% if nets.rows %}
  <div class="grid">
    <section class="card"><h2>Network sizes (incidents in view)</h2><div class="body">
      <div class="plot"><canvas id="c-net" role="img" aria-label="Bar chart of incidents in view per candidate network"></canvas></div>
      <p class="hint">{{ nets.rows|length }} candidate network(s); {{ nets.unlinked }} incident(s) in view are not in any network.</p>
    </div></section>
    <section class="card"><h2>Networks at a glance</h2><div class="body">
      <table class="wide"><tr><th>Network</th><th>In view / total</th><th>Active</th><th>Areas</th><th>Strongest link</th></tr>
        {% for r in nets.rows %}<tr><td class="mono"><strong>{{ r.id }}</strong></td><td>{{ r.in_view }} / {{ r.size }}</td>
          <td class="nowrap">{{ r.first or '?' }} &ndash; {{ r.last or '?' }}</td><td>{{ r.areas }}</td>
          <td class="nowrap">{% if r.best_band %}{{ '%.2f'|format(r.best) }} <span class="band band-{{ r.best_band }}">{{ r.best_band }}</span>{% endif %}</td></tr>{% endfor %}
      </table>
    </div></section>
    <section class="card wide"><h2>What each network has in common</h2><div class="body">
      <table class="wide"><tr><th>Network</th><th>Common signature (shared by most members)</th><th>Members in view</th></tr>
        {% for r in nets.rows %}<tr><td class="mono"><strong>{{ r.id }}</strong></td>
          <td><div class="chips">{% for x in r.signature %}<span class="chip">{{ x }}</span>{% else %}<span class="missing">none shared by most members</span>{% endfor %}</div></td>
          <td class="missing">{{ r.members|join(', ') }}</td></tr>{% endfor %}
      </table>
    </div></section>
  </div>
  {% else %}<p class="empty">No candidate network has a member in view.</p>{% endif %}

  <h2 class="sec" id="links">Links and review</h2>
  <p class="lede">How strong the {{ strength.total }} link(s) between incidents in view are, and how many an analyst has reviewed.</p>
  <div class="tiles">
    {% for b in strength.bands %}<div class="tile"><div class="k">{{ b.band }} links</div><div class="v">{{ b.n }}</div>
      <div class="s">{{ {'strong':'score 0.66 or more','medium':'score 0.40 to 0.66','weak':'score 0.25 to 0.40'}[b.band] }}</div></div>{% endfor %}
    <div class="tile"><div class="k">Reviewed</div><div class="v">{{ strength.reviewed_pct }}%</div>
      <div class="s">of links in view (<a href="{{ url_for('review.review_page', show='open') }}">review the rest</a>)</div></div>
  </div>
  <div class="grid">
    <section class="card"><h2>Link score distribution</h2><div class="body">
      <div class="plot"><canvas id="c-hist" role="img" aria-label="Histogram of link scores"></canvas></div>
      <details><summary>Show table</summary><table><tr><th>Score</th><th>Links</th></tr>
        {% for l in strength.hist_labels %}<tr><td>{{ l }}</td><td class="n">{{ strength.hist_values[loop.index0] }}</td></tr>{% endfor %}
      </table></details>
    </div></section>
    <section class="card"><h2>Analyst review progress</h2><div class="body">
      <div class="meters" style="grid-template-columns:1fr">
        {% for r in strength.review %}<div class="mrow"><div class="top"><b>{{ r.label }}</b><span>{{ r.n }} &middot; {{ r.pct }}%</span></div>
          <div class="meter" role="img" aria-label="{{ r.label }}: {{ r.pct }} percent"><span style="width:{{ r.pct }}%"></span></div></div>{% endfor %}
      </div>
      <p class="hint">Decisions are stored separately from the machine's scores and can always be undone.</p>
    </div></section>
  </div>

  <h2 class="sec" id="quality">Data quality</h2>
  <p class="lede">Which fields the reports in view carry, as found by Sirens in the report text. Low values can mean the
    reports do not mention the field, or that the wording is not in the taxonomy yet.</p>
  <div class="grid">
    <section class="card wide"><h2>Completeness by field &middot; overall {{ qual.overall }}%</h2><div class="body">
      <div class="meters">
        {% for r in qual.fields %}<div class="mrow"><div class="top"><b>{{ r.label }}</b><span>{{ r.n }} / {{ shown|length }} &middot; {{ r.pct }}%</span></div>
          <div class="meter" role="img" aria-label="{{ r.label }}: {{ r.pct }} percent"><span style="width:{{ r.pct }}%"></span></div></div>{% endfor %}
      </div>
    </div></section>
    <section class="card wide"><h2>Least complete reports</h2><div class="body">
      <table class="wide"><tr><th>Incident</th><th>Place &middot; date</th><th>Complete</th><th>Missing</th></tr>
        {% for r in qual.weakest %}<tr><td class="mono"><strong>{{ r.id }}</strong></td><td class="nowrap">{{ r.location }} &middot; {{ r.date }}</td>
          <td>{{ r.pct }}%</td><td class="missing">{{ r.missing|join(', ') or 'nothing' }}</td></tr>{% endfor %}
      </table>
      <p class="hint">Completeness = share of the {{ qual.n_fields }} fields above that a report carries.</p>
    </div></section>
  </div>
  {% endif %}
  {% endif %}
</div>

<script src="{{ url_for('static', filename='vendor/chart.umd.js') }}"></script>
<script id="dash-data" type="application/json">{{ charts|tojson }}</script>
<script>
(function(){
  if (!window.Chart || !document.getElementById('c-timeline')) return;
  var D = JSON.parse(document.getElementById('dash-data').textContent);
  var ACCENT = '#a8703a', MUTED = '#c4cbc6', GRID = '#eef0ee', TICK = '#7a8791';
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = TICK;
  function axes(horizontal){
    var value = {beginAtZero: true, ticks: {precision: 0}, grid: {color: GRID}, border: {display: false}};
    var cat = {grid: {display: false}, border: {color: '#e2e6e3'}};
    return horizontal ? {x: value, y: cat} : {x: cat, y: value};
  }
  function bar(id, data, horizontal, onPick, unit){
    unit = unit || 'incident(s)';
    // Grouped bars ("Other", "not recorded") are not one category: draw them muted.
    var n = data.keys ? data.keys.length : data.values.length;
    var fill = data.values.map(function(_, i){ return i < n ? ACCENT : MUTED; });
    return new Chart(document.getElementById(id), {
      type: 'bar',
      data: {labels: data.labels, datasets: [{label: 'Incidents', data: data.values,
             backgroundColor: fill, hoverBackgroundColor: fill.map(function(c){ return c === ACCENT ? '#8c5a2b' : '#aeb6b1'; }),
             borderRadius: 4, borderSkipped: 'start',
             categoryPercentage: 0.8, barPercentage: 0.9, maxBarThickness: horizontal ? 22 : 34}]},
      options: {indexAxis: horizontal ? 'y' : 'x', responsive: true, maintainAspectRatio: false,
                animation: false, plugins: {legend: {display: false},
                tooltip: {displayColors: false, callbacks: {label: function(c){
                  return c.parsed[horizontal ? 'x' : 'y'] + ' ' + unit; }}}},
                scales: axes(horizontal),
                onHover: function(e, els){ e.native.target.style.cursor = (onPick && els.length) ? 'pointer' : 'default'; },
                onClick: function(e, els){ if (onPick && els.length) onPick(els[0].index); }}
    });
  }
  function filterBy(name, keys){
    return function(i){
      if (i >= keys.length) return;          // "Other" / "not recorded" have no single value
      var u = new URL(window.location.href);
      u.searchParams.set(name, keys[i]);
      window.location.href = u.toString();
    };
  }
  bar('c-timeline', D.timeline, false, null);
  bar('c-area', D.area, true, filterBy('area', D.area.keys));
  bar('c-init', D.initiation, true, filterBy('initiation', D.initiation.keys));
  if (document.getElementById('c-net')) bar('c-net', D.networks, true, null, 'incident(s) in view');
  var hist = bar('c-hist', D.hist, false, null, 'link(s)');
  // Axis shows where each 0.05-wide bin starts; tooltip and table give the full range.
  hist.options.scales.x.ticks = {maxRotation: 0, autoSkip: true,
    callback: function(v){ return this.getLabelForValue(v).split('–')[0]; }};
  hist.options.plugins.tooltip.callbacks.title = function(items){ return 'score ' + items[0].label; };
  hist.update();

  // Signature breakdown: one chart, the selector swaps which feature it shows.
  var sel = document.getElementById('facet');
  var facet = sel.value;
  var sigChart = bar('c-sig', D.signatures[facet], true, function(i){
    var keys = D.signatures[facet].keys;
    filterBy('feature', keys.map(function(k){ return facet + ':' + k; }))(i);
  });
  sel.addEventListener('change', function(){
    facet = sel.value;
    var d = D.signatures[facet], n = d.keys.length;
    var fill = d.values.map(function(_, i){ return i < n ? ACCENT : MUTED; });
    sigChart.data.labels = d.labels;
    sigChart.data.datasets[0].data = d.values;
    sigChart.data.datasets[0].backgroundColor = fill;
    sigChart.data.datasets[0].hoverBackgroundColor = fill.map(function(c){ return c === ACCENT ? '#8c5a2b' : '#aeb6b1'; });
    sigChart.update();
    document.querySelectorAll('.sig-table').forEach(function(t){ t.hidden = t.dataset.facet !== facet; });
  });
})();
</script>
</body>
</html>
"""
