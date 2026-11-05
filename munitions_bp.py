"""Munitions reference: every public reference entry, grouped by family.

Search and family filters run in the browser (no network). Each entry is a
card that opens in place to show its specs, categories, how it is
encountered, the responder note and its sources, plus how many reports on
record mention that object type. Recognition and cataloguing only: the
library-wide disclaimer stays at the top, and each entry keeps its own
"do not approach" note.
"""
from __future__ import annotations

import re
from collections import Counter

from flask import Blueprint, render_template_string

import ui_icons
from linker import reference, store

munitions_bp = Blueprint("munitions", __name__)


def entries() -> list[dict]:
    """Reference entries with their family and how often the record mentions them."""
    seen = Counter(v for i in store.all_incidents()
                   for v in {v for (k, v) in i.feature_keys() if k == "object_type"})
    out = []
    for e in reference.all_entries():
        fam = ui_icons.family_of(e["object_type"])
        out.append({**e, "family": fam, "family_name": ui_icons.FAMILY_NAME[fam],
                    "seen": seen.get(e["object_type"], 0)})
    order = {k: n for n, (k, _l, _i) in enumerate(ui_icons.FAMILIES)}
    out.sort(key=lambda e: (order[e["family"]], _natural(e.get("label", ""))))
    return out


def _natural(label: str):
    """Sort key so calibres run 60, 81, 82, 120 mm (not 120 before 60);
    entries without a number (the generic ones) come last in their family."""
    m = re.search(r"\d+", label)
    return (m is None, int(m.group()) if m else 0, label.lower())


@munitions_bp.route("/munitions")
def munitions_page():
    items = entries()
    counts = Counter(e["family"] for e in items)
    families = [(k, n, i, counts[k]) for k, n, i in ui_icons.FAMILIES if counts[k]]
    return render_template_string(_TEMPLATE, items=items, families=families,
                                  disclaimer=reference.disclaimer(), icon=ui_icons.icon)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens — Munitions reference</title>
<link rel="stylesheet" href="{{ url_for('static', filename='sirens.css') }}">
</head>
<body>
<div class="bar">
  <a class="brand" href="{{ url_for('home.home_page') }}">Sirens<small>C-IED Incident Link Console</small></a>
  {{ sirens_menu('munitions') }}
</div>

<main class="wrap">
  <div class="mhead">
    <div>
      <h1>Munitions reference</h1>
      <p>{{ items|length }} types in {{ families|length }} families. Open a card for its description, specifications and how it is usually found.</p>
    </div>
    <label class="search">{{ icon('search') }}<span class="sr">Search the reference</span>
      <input id="q" type="search" placeholder="Search, e.g. 122 mm, mortar, cluster" autocomplete="off"></label>
  </div>

  <div class="safety" role="note">{{ icon('warning') }}<div>{{ disclaimer }}</div></div>

  <div class="fams" role="group" aria-label="Filter by family">
    <button type="button" class="fam" data-fam="" aria-pressed="true">All <span class="n">{{ items|length }}</span></button>
    {% for key, name, ic, n in families %}
      <button type="button" class="fam" data-fam="{{ key }}" aria-pressed="false">{{ icon(ic) }}{{ name }} <span class="n">{{ n }}</span></button>
    {% endfor %}
  </div>

  <p id="count" class="sr" aria-live="polite"></p>
  <div class="grid" id="cards">
    {% for e in items %}
    <details class="mcard" id="ref-{{ e.object_type }}" data-fam="{{ e.family }}"
             data-text="{{ (e.label ~ ' ' ~ e.family_name ~ ' ' ~ (e.summary or '') ~ ' ' ~ (e.specs|map('join', ' ')|join(' ')))|lower }}">
      <summary>
        <span class="icon">{{ icon(e.family) }}</span>
        <h3>{{ e.label }}</h3>
        <span class="famname">{{ e.family_name }}</span>
        {% if e.summary %}<p class="sum">{{ e.summary }}</p>{% endif %}
        {% if e.seen %}<span class="seen">Mentioned in {{ e.seen }} report{{ 's' if e.seen != 1 }} on record</span>{% endif %}
      </summary>
      <div class="mbody">
        {% if e.specs %}<div><h4>Specifications</h4><table>
          {% for k, v in e.specs %}<tr><th scope="row">{{ k }}</th><td>{{ v }}</td></tr>{% endfor %}</table></div>{% endif %}
        {% if e.ammunition %}<div><h4>Categories</h4><ul>{% for a in e.ammunition %}<li>{{ a }}</li>{% endfor %}</ul></div>{% endif %}
        {% if e.deployment %}<div><h4>How it is found</h4><ul>{% for a in e.deployment %}<li>{{ a }}</li>{% endfor %}</ul></div>{% endif %}
        {% if e.responder_note %}<div class="note" role="note">{{ icon('warning') }}<div>{{ e.responder_note }}</div></div>{% endif %}
        {% if e.sources %}<div class="src">Sources: {{ e.sources|join('; ') }}. Figures are approximate and vary by model.</div>{% endif %}
      </div>
    </details>
    {% endfor %}
  </div>
  <p class="nomatch" id="none" hidden>No type matches that search. Try a calibre (122 mm) or a family name, or show all families.</p>
</main>
<footer>Public, category-level reference for recognition and cataloguing. It does not identify a specific object and gives no handling guidance.</footer>
<script>
(function(){
  var q = document.getElementById('q'), cards = [].slice.call(document.querySelectorAll('.mcard')),
      chips = [].slice.call(document.querySelectorAll('.fam')), none = document.getElementById('none'),
      count = document.getElementById('count'), fam = '';
  function apply(){
    var words = q.value.toLowerCase().split(/\s+/).filter(Boolean), shown = 0;
    cards.forEach(function(c){
      var t = c.getAttribute('data-text'), ok = (!fam || c.getAttribute('data-fam') === fam) &&
        words.every(function(w){ return t.indexOf(w) >= 0; });
      c.hidden = !ok; if (ok) shown++;
    });
    none.hidden = shown > 0;
    count.textContent = shown + ' types shown';
  }
  chips.forEach(function(b){ b.addEventListener('click', function(){
    fam = b.getAttribute('data-fam');
    chips.forEach(function(o){ o.setAttribute('aria-pressed', o === b ? 'true' : 'false'); });
    history.replaceState(null, '', fam ? '#' + fam : location.pathname);
    apply();
  }); });
  q.addEventListener('input', apply);
  // One card open at a time keeps the page readable.
  cards.forEach(function(c){ c.addEventListener('toggle', function(){
    if (c.open) cards.forEach(function(o){ if (o !== c) o.open = false; });
  }); });
  // #mortar opens a family; #ref-mortar_81mm opens one card.
  var h = location.hash.slice(1);
  if (h.indexOf('ref-') === 0) { var c = document.getElementById(h); if (c) { c.open = true; c.scrollIntoView(); } }
  else if (h) { chips.forEach(function(b){ if (b.getAttribute('data-fam') === h) b.click(); }); }
})();
</script>
</body>
</html>
"""
