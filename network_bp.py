"""Likely network for a saved report: which candidate network it falls into, and why.

A standalone Flask Blueprint (wired into app.py with one line). The console's
result card loads /network/<id>/panel with htmx right after a report is saved.
The panel runs the same matcher and clustering as the link tree (threshold
0.25, Louvain with a fixed seed) over every stored incident, finds the
network the report falls into, and lists the report's links into it with
score, band (computed in code) and the machine's reasons.

It is a lead for an analyst, never a conclusion: it states what the record
shows and points to /review, where links are confirmed or rejected.
"""
from __future__ import annotations

from flask import Blueprint, render_template_string

from linker import decisions, store
from linker.ai import _score_band
from linker.cluster import Clusterer
from linker.match import Matcher
import report_view

network_bp = Blueprint("network", __name__)

THRESHOLD = 0.25          # same as /tree and /review


def likely_network(incident_id: str) -> dict | None:
    """The report's network and its links into it; None if it is not on record."""
    incidents = store.all_incidents()
    by_id = {i.incident_id: i for i in incidents}
    if incident_id not in by_id:
        return None
    links = Matcher().fit(incidents).all_pairs(incidents, threshold=THRESHOLD)
    clusters = Clusterer(incidents, links).clusters(singletons=False)
    cluster = next((c for c in clusters if incident_id in c.members), None)
    if cluster is None:
        return {"incident_id": incident_id, "cluster": None, "links": []}
    members = set(cluster.members)
    decided = decisions.current_decisions()
    own = []
    for l in links:
        if incident_id in (l.a, l.b):
            other = l.b if l.a == incident_id else l.a
            if other in members:
                own.append({"other": by_id[other], "score": l.score, "band": _score_band(l.score),
                            "reasons": l.reasons,
                            "decision": decided.get(tuple(sorted((l.a, l.b))))})
    own.sort(key=lambda x: x["score"], reverse=True)
    return {"incident_id": incident_id, "cluster": cluster, "links": own,
            "best": own[0] if own else None}


@network_bp.route("/network/<path:incident_id>/panel")
def panel(incident_id):
    net = likely_network(incident_id)
    if net is None:
        return render_template_string(
            '<h2>Likely network</h2><div class="body"><div class="empty">'
            '{{ i }} is not on record, so it has no network.</div></div>', i=incident_id), 404
    return render_template_string(_PANEL, n=net, feature_label=report_view.feature_label,
                                  reason_label=report_view.reason_label)


_PANEL = r"""<h2>Likely network</h2>
<div class="body net-panel">
{% if not n.cluster %}
  <p class="empty">No likely network yet: no stored incident links to {{ n.incident_id }} with a
    score of 0.25 or more and shared evidence. It will be re-checked every time the record changes.</p>
{% else %}
  {% set c = n.cluster %}
  <p class="net-lead">Clustering places it in candidate network <strong class="mono">{{ c.cluster_id }}</strong>
    ({{ c.size }} incidents). Strongest link: <strong class="mono">{{ n.best.other.incident_id }}</strong>,
    score <span class="mono">{{ '%.2f'|format(n.best.score) }}</span> (<strong>{{ n.best.band }}</strong>).
    {% if n.best.band == 'weak' %}Every link into this network is weak, so treat the placement as tentative.{% endif %}</p>
  <h3 class="subhead">Network members</h3>
  <div class="chips">{% for m in c.members %}<span class="chip{{ ' ent' if m == n.incident_id else '' }}">{{ m }}</span>{% endfor %}</div>
  {% if c.signature %}
  <h3 class="subhead">What most members share</h3>
  <div class="chips">{% for s in c.signature %}<span class="chip sig">{{ feature_label(s) }}</span>{% endfor %}</div>
  {% endif %}
  <h3 class="subhead">This report's links into the network</h3>
  {% for x in n.links %}
  <div class="match {{ x.band }}">
    <div class="top">
      <span class="band {{ x.band }}">{{ x.band|capitalize }}</span>
      <span class="mid mono">{{ x.other.incident_id }}</span>
      <span class="loc">{{ x.other.location or 'No location' }}{% if x.other.date %}, {{ x.other.date }}{% endif %}
        {% if x.decision %}. Analyst: {{ x.decision }}{% endif %}</span>
      <span class="score">{{ '%.2f'|format(x.score) }}</span>
    </div>
    {% if x.reasons %}<ul class="reasons">{% for r in x.reasons %}<li>{{ reason_label(r) }}</li>{% endfor %}</ul>{% endif %}
  </div>
  {% endfor %}
{% endif %}
  <p class="note">A lead for an analyst, not a conclusion. Bands are
    computed in code (weak &lt; 0.40 &le; medium &lt; 0.66 &le; strong). Confirm or reject these links on
    <a href="{{ url_for('review.review_page') }}">review links</a>; see the whole picture on the
    <a href="{{ url_for('link_tree') }}">link tree</a>.</p>
</div>
"""
