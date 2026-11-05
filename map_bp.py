"""Offline street map of Lebanon (/map): OpenStreetMap data, no network.

The street map is one PMTiles file (data/map/lebanon.pmtiles, not in git; see
scripts/map/get_map.sh) drawn by the vendored MapLibre GL JS with the vendored
pmtiles reader. Flask serves the file with HTTP Range support, so the browser
only reads the parts it needs. The style (static/map/style.json) and the label
fonts (static/map/fonts/) are local too; the browser only ever asks 127.0.0.1.

Everything outside Lebanon is masked and panning is limited to the country.
Lebanon's outline is the outer edge of the caza shapes in data/regions.json.

Incidents are drawn as markers. Their position is only as precise as the
record: a filed grid reference gives an exact point; otherwise a report is
placed at its caza (district), spread around the caza centre so markers do not
sit on top of each other. Popups say which applies.

If the map file is missing the page says so and still lists the incidents.
"""
from __future__ import annotations

import json
import math
import pathlib
from functools import lru_cache

from flask import Blueprint, abort, current_app, jsonify, render_template_string, send_file

ROOT = pathlib.Path(__file__).resolve().parent
REGIONS_FILE = ROOT / "data" / "regions.json"
DEFAULT_MAP_FILE = ROOT / "data" / "map" / "lebanon.pmtiles"
ATTRIBUTION = "© OpenStreetMap contributors"

map_bp = Blueprint("offmap", __name__)


def map_file() -> pathlib.Path:
    return pathlib.Path(current_app.config.get("SIRENS_MAP_FILE") or DEFAULT_MAP_FILE)


# ---------------------------------------------------------------- geometry
def _rings(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    return [r for poly in geom["coordinates"] for r in poly]


def _area(ring):
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))


@lru_cache(maxsize=1)
def _regions():
    try:
        return json.loads(REGIONS_FILE.read_text())
    except (OSError, ValueError):
        return {"features": []}


@lru_cache(maxsize=1)
def lebanon_border() -> list:
    """Lebanon's outline as one closed ring of [lon, lat].

    Edges shared by two neighbouring cazas cancel out; the edges left over are
    the national border. Chained into rings, the largest one is the country
    (the others are zero-area slivers where neighbouring shapes do not meet
    exactly)."""
    key = lambda p: (round(p[0], 6), round(p[1], 6))
    count = {}
    for f in _regions()["features"]:
        for ring in _rings(f["geometry"]):
            for a, b in zip(ring, ring[1:]):
                a, b = key(a), key(b)
                if a != b:
                    e = frozenset((a, b))
                    count[e] = count.get(e, 0) + 1
    adj = {}
    for e, c in count.items():
        if c == 1:
            a, b = tuple(e)
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    best = []
    while any(adj.values()):
        start = next(v for v, n in adj.items() if n)
        ring, cur = [start], start
        while adj[cur]:
            nxt = adj[cur].pop()
            adj[nxt].discard(cur)
            if nxt == start:
                break
            ring.append(nxt)
            cur = nxt
        if not best or abs(_area(ring)) > abs(_area(best)):
            best = ring
    return [list(p) for p in best] + ([list(best[0])] if best else [])


@lru_cache(maxsize=1)
def caza_centres() -> dict:
    """{caza name: (lon, lat)} — the area-weighted centre of each caza's largest piece."""
    out, size = {}, {}
    for f in _regions()["features"]:
        name = f["properties"]["name"]
        for ring in _rings(f["geometry"]):
            a = _area(ring)
            if not a or abs(a) <= size.get(name, 0):
                continue
            cx = sum((x1 + x2) * (x1 * y2 - x2 * y1) for (x1, y1), (x2, y2) in zip(ring, ring[1:])) / (6 * a)
            cy = sum((y1 + y2) * (x1 * y2 - x2 * y1) for (x1, y1), (x2, y2) in zip(ring, ring[1:])) / (6 * a)
            out[name], size[name] = (round(cx, 5), round(cy, 5)), abs(a)
    return out


def bounds():
    b = lebanon_border()
    if not b:
        return [35.0, 33.0, 36.7, 34.75]
    xs, ys = [p[0] for p in b], [p[1] for p in b]
    return [min(xs), min(ys), max(xs), max(ys)]


def spread(lon, lat, idx):
    """Display offset for the idx-th caza-level report: a small golden-angle spiral
    (about 1-4 km) so markers placed at the same caza centre do not overlap."""
    if idx <= 0:
        return lon, lat
    ang = idx * 2.399963229728653
    rad = min(0.008 + 0.006 * math.sqrt(idx), 0.035)
    return lon + rad * math.cos(ang) / math.cos(math.radians(lat)), lat + rad * math.sin(ang)


# ---------------------------------------------------------------- routes
@map_bp.route("/map/data/lebanon.pmtiles")
def pmtiles_file():
    path = map_file()
    if not path.is_file():
        abort(404)
    # conditional=True gives HTTP Range (206 Partial Content) support.
    return send_file(path, mimetype="application/octet-stream", conditional=True, max_age=3600)


@map_bp.route("/map/border.geojson")
def border_geojson():
    return jsonify({"type": "Feature", "properties": {"name": "Lebanon"},
                    "geometry": {"type": "LineString", "coordinates": lebanon_border()}})


@map_bp.route("/map/cazas.geojson")
def cazas_geojson():
    """Caza (district) outlines, for the place picker on the report form."""
    return jsonify(_regions())


@map_bp.route("/map/mask.geojson")
def mask_geojson():
    """A world-sized polygon with Lebanon cut out, drawn over everything outside it."""
    world = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]
    return jsonify({"type": "Feature", "properties": {},
                    "geometry": {"type": "Polygon", "coordinates": [world, lebanon_border()]}})


def render_page(incidents, legend, unplaced=0):
    """The /map page. incidents: dicts with id, lon, lat, exact, date, loc, street,
    typelabel, fill, item_color, condition, snip, grid."""
    return render_template_string(
        _PAGE, incidents=incidents, legend=legend, have_map=map_file().is_file(),
        bounds=bounds(), attribution=ATTRIBUTION, unplaced=unplaced)


_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sirens — Map</title>
<link rel="stylesheet" href="{{ url_for('static', filename='sirens.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='vendor/maplibre-gl/maplibre-gl.css') }}">
<style>
  html,body{height:100%}
  /* The map fills the viewport under the header; only the side list scrolls. */
  body{display:flex;flex-direction:column;height:100vh;overflow:hidden}
  .stage{flex:1;display:grid;grid-template-columns:minmax(0,1fr) 360px;grid-template-rows:minmax(0,1fr);min-height:0}
  @media(max-width:900px){body{height:auto;overflow:visible}
    .stage{grid-template-columns:1fr;grid-template-rows:62vh auto}}
  #map{position:relative;min-height:420px;background:#eef1ee}
  .side{background:#fff;border-left:1px solid var(--line);overflow-y:auto;display:flex;flex-direction:column}
  @media(max-width:900px){.side{border-left:0;border-top:1px solid var(--line)}}
  .side-head{padding:18px 18px 12px;border-bottom:1px solid var(--line-2);position:sticky;top:0;background:#fff;z-index:2}
  .side-head h1{font-size:19px;margin:0 0 2px}
  .side-head .count{font-size:13.5px;color:var(--muted);margin:0 0 12px}
  .side input[type=search],.side select{width:100%;font:14.5px var(--sans);padding:9px 11px;border:1px solid #cfd6d3;
    border-radius:8px;background:#fff;color:var(--ink)}
  .filters{display:grid;gap:10px}
  .row2{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center}
  .switch{display:inline-flex;align-items:center;gap:7px;font-size:13.5px;color:var(--ink-soft);white-space:nowrap;cursor:pointer}
  .switch input{width:16px;height:16px;accent-color:var(--ink)}
  .types{display:flex;flex-wrap:wrap;gap:6px}
  .type{display:inline-flex;align-items:center;gap:7px;font:13px/1 var(--sans);padding:6px 10px 6px 8px;border-radius:20px;
    border:1px solid var(--line);background:#fff;color:var(--ink-soft);cursor:pointer}
  .type .n{color:var(--muted)}
  .type[aria-pressed="false"]{opacity:.45;text-decoration:line-through}
  .dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}
  .dot.approx{box-shadow:inset 0 0 0 2.5px var(--c)}
  .list{padding:10px 12px 18px}
  .inc{display:grid;grid-template-columns:auto 1fr auto;gap:2px 10px;align-items:center;width:100%;text-align:left;
    background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:0 0 8px;cursor:pointer;font:inherit;color:inherit}
  .inc:hover,.inc:focus-visible,.inc.on{border-color:var(--sig)}
  .inc[hidden]{display:none}
  .inc b{font-family:var(--mono);font-size:13px;font-weight:600}
  .inc .t{font-size:13.5px;color:var(--ink-soft);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .inc small{grid-column:2/4;color:var(--muted);font-size:12.5px}
  .inc .pos{font-size:12px;color:var(--muted);white-space:nowrap}
  .none{color:var(--muted);text-align:center;padding:20px}
  .notes{padding:4px 18px 22px;font-size:13px;color:var(--muted)}
  .notes p{margin:0 0 10px}
  .banner{position:absolute;z-index:4;top:10px;left:50%;transform:translateX(-50%);max-width:calc(100% - 120px);
    background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 14px;font-size:13.5px;
    box-shadow:0 2px 8px rgba(22,32,43,.12);color:var(--ink-soft)}
  .banner code{font-family:var(--mono);background:var(--line-2);padding:1px 5px;border-radius:4px}
  .missing{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:24px}
  .missing .card{max-width:520px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:22px 24px}
  .missing h1{font-size:17px;margin:0 0 8px}
  .tip{position:absolute;z-index:5;pointer-events:none;background:#fff;border:1px solid var(--line);border-radius:7px;
    padding:6px 9px;font-size:12.5px;box-shadow:0 2px 6px rgba(22,32,43,.1),0 8px 20px rgba(22,32,43,.12);display:none;max-width:280px}
  .tip .ref{font-family:var(--mono);font-size:11.5px;color:var(--ink-soft)}
  .maplibregl-popup-content{font-family:var(--sans);font-size:13.5px;border-radius:10px;padding:14px 16px;max-width:320px}
  .pop h3{font-size:15px;margin:0 0 2px;display:flex;align-items:center;gap:8px}
  .pop h3 b{font-family:var(--mono)}
  .pop .meta{color:var(--muted);font-size:12.5px;margin:0 0 8px}
  .pop dl{margin:0 0 8px;display:grid;grid-template-columns:auto 1fr;gap:3px 10px}
  .pop dt{color:var(--muted)}
  .pop dd{margin:0}
  .pop .approx{font-size:12px;color:var(--sig-deep);background:var(--sig-soft);border-radius:5px;padding:3px 7px;display:inline-block}
  .pop .exact{font-size:12px;color:var(--strong);background:var(--strong-bg);border-radius:5px;padding:3px 7px;display:inline-block}
  .pop .snip{color:var(--ink-soft);font-size:13px;margin:8px 0 0}
  .pop button{margin-top:10px;font:600 13px var(--sans);padding:7px 11px;border-radius:6px;border:1px solid var(--ink);background:#fff;cursor:pointer}
  .readout{position:absolute;z-index:4;left:50%;bottom:14px;transform:translateX(-50%);background:rgba(255,255,255,.96);
    border:1px solid var(--line);border-radius:999px;padding:7px 16px;font-size:13px;color:var(--ink-soft);
    box-shadow:0 2px 8px rgba(22,32,43,.12);white-space:nowrap}
  .readout b{font-family:var(--mono);color:var(--ink);font-weight:600}
  .readout.copied{border-color:#c9dcc6;background:#e7efe5;color:#3d6b45}
</style>
</head><body>
<div class="bar"><a class="brand" href="{{ url_for('home.home_page') }}">Sirens<small>C-IED Incident Link Console</small></a>{{ sirens_menu('map') }}</div>
<div class="stage">
  <div id="map" role="region" aria-label="Map of Lebanon with incident markers">
    {% if not have_map %}
    <div class="banner" role="status">Offline map not installed — run <code>bash setup.sh</code>. Showing district outlines only.</div>
    {% endif %}
  </div>
  <aside class="side" aria-label="Incidents">
    <div class="side-head">
      <h1>Incidents on the map</h1>
      <p class="count" id="count" aria-live="polite">{{ incidents|length }} shown{% if unplaced %}; {{ unplaced }} without a caza or grid are not on the map{% endif %}</p>
      <div class="filters">
        <input type="search" id="q" placeholder="Search ID, place or text" aria-label="Search incidents">
        <div class="row2">
          <select id="caza" aria-label="Caza">
            <option value="">All cazas</option>
            {% for c in incidents|map(attribute='caza')|reject('equalto', '')|unique|sort %}<option>{{ c }}</option>{% endfor %}
          </select>
          <label class="switch"><input type="checkbox" id="exact"> Exact grid only</label>
        </div>
        {% if legend %}<div class="types" role="group" aria-label="Show types">
          {% for t in legend %}<button type="button" class="type" data-type="{{ t.key }}" aria-pressed="true">
            <i class="dot" style="background:{{ t.color }}"></i>{{ t.label }} <span class="n">{{ t.count }}</span></button>{% endfor %}
        </div>{% endif %}
      </div>
    </div>
    <div class="list">
      {% for i in incidents %}
      <button type="button" class="inc" data-id="{{ i.id }}">
        <i class="dot{{ '' if i.exact else ' approx' }}" style="background:{{ i.fill if i.exact else '#fff' }};--c:{{ i.fill }}"></i>
        <span class="t"><b>{{ i.id }}</b> {{ i.typelabel }}</span>
        <span class="pos">{{ 'exact' if i.exact else 'approx.' }}</span>
        <small>{{ i.loc or 'no location' }} · {{ i.date or 'no date' }}</small></button>
      {% else %}<p class="none">No incidents could be placed. Load the demo data or file a report with a caza.</p>{% endfor %}
      <p class="none" id="nomatch" hidden>No incident matches these filters.</p>
    </div>
    <div class="notes">
      <p>A solid marker is an exact position from a filed grid reference. A hollow marker is approximate: the report
        is placed at its caza and spread around the centre.</p>
      <p>MGRS grid: 100 km squares when zoomed out, 10 km lines at district zoom, 1 km lines up close. Move over the
        map to read a reference; click to copy it. Lebanon spans zones 36S and 37S, which meet at 36°E in the Bekaa:
        the grid jumps at that line, which is correct.</p>
      <p>Map data {{ attribution }}. Street map shown for orientation only.</p>
    </div>
  </aside>
</div>
<script id="map-data" type="application/json">{{ {'incidents': incidents, 'bounds': bounds, 'have_map': have_map}|tojson }}</script>
<script src="{{ url_for('static', filename='vendor/pmtiles/pmtiles.js') }}"></script>
<script src="{{ url_for('static', filename='vendor/mgrs/mgrs.min.js') }}"></script>
<script src="{{ url_for('static', filename='map/mgrs_grid.js') }}"></script>
<script type="module">
import * as maplibregl from "{{ url_for('static', filename='vendor/maplibre-gl/maplibre-gl.mjs') }}";
const D = JSON.parse(document.getElementById('map-data').textContent);
const [x0, y0, x1, y1] = D.bounds;
// Panning limit: Lebanon is tall and narrow, so allow more room east-west, or a wide
// screen could never zoom out to the whole country. Outside Lebanon is greyed out.
const padX = 1.6, padY = 0.35;
window.sirensMapReady = false;

function popupNode(i) {
  const el = document.createElement('div'); el.className = 'pop';
  const add = (parent, tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; parent.appendChild(n); return n; };
  const h = add(el, 'h3'); const d = add(h, 'i', 'dot'); d.style.background = i.fill; add(h, 'b', '', i.id); add(h, 'span', '', i.typelabel);
  add(el, 'div', 'meta', [i.date || 'no date', i.loc || 'no location'].join(' · '));
  const dl = add(el, 'dl');
  const row = (k, v) => { if (v) { add(dl, 'dt', '', k); add(dl, 'dd', '', v); } };
  row('Place', i.street); row('Colour', i.item_color);
  row('Condition', (i.condition || []).join(', '));
  row('MGRS', i.mgrs && (i.mgrs + (i.exact ? '' : ' (approx., caza centre)')));
  add(el, 'span', i.exact ? 'exact' : 'approx', i.exact ? 'Exact: from the filed grid reference' : 'Approximate: placed at the caza centre');
  if (i.snip) add(el, 'p', 'snip', i.snip);
  if (i.mgrs) {
    const b = add(el, 'button', '', 'Copy MGRS'); b.type = 'button';
    b.addEventListener('click', async () => { b.textContent = (await copyText(i.mgrs)) ? 'Copied' : 'Could not copy'; });
  }
  return el;
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (err) {
    const t = Object.assign(document.createElement('textarea'), {value: text}); document.body.appendChild(t); t.select();
    const ok = document.execCommand('copy'); t.remove(); return ok; }
}

const points = {type: 'FeatureCollection', features: D.incidents.map(i => ({
  type: 'Feature', id: i.id, properties: {id: i.id, fill: i.fill, exact: i.exact, type: i.type, caza: i.caza},
  geometry: {type: 'Point', coordinates: [i.lon, i.lat]}}))};
const byId = Object.fromEntries(D.incidents.map(i => [i.id, i]));

{
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol('pmtiles', protocol.tile);
  let style = null;
  try { style = await (await fetch("{{ url_for('static', filename='map/style.json') }}")).json(); }
  catch (e) {   // e.g. the page is being left while it loads; say so calmly instead of failing
    const box = document.createElement('div'); box.className = 'missing';
    box.innerHTML = '<div class="card" role="status"><h1>The map style could not be loaded</h1>' +
      '<p>Reload the page. The incidents are listed on the right.</p></div>';
    document.getElementById('map').appendChild(box);
  }
  if (style) {
  if (D.have_map) style.sources.protomaps.url = 'pmtiles://' + location.origin + "{{ url_for('offmap.pmtiles_file') }}";
  else {   // no street map: keep the background and the local fonts, drop the tiles
    delete style.sources.protomaps;
    style.layers = style.layers.filter(l => !l.source);
  }
  const map = new maplibregl.Map({
    container: 'map', style, bounds: [[x0, y0], [x1, y1]], fitBoundsOptions: {padding: 20},
    maxBounds: [[x0 - padX, y0 - padY], [x1 + padX, y1 + padY]], minZoom: 6.5, maxZoom: 17,
    attributionControl: {compact: false}, dragRotate: false, pitchWithRotate: false,
  });
  window.sirensMap = map;
  map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-left');
  map.addControl(new maplibregl.ScaleControl({unit: 'metric'}), 'bottom-left');

  map.on('load', () => {
    map.resize();                                  // the page layout settles after the map is created
    map.fitBounds([[x0, y0], [x1, y1]], {padding: 20, animate: false});
    map.addSource('mask', {type: 'geojson', data: "{{ url_for('offmap.mask_geojson') }}"});
    map.addLayer({id: 'outside-lebanon', type: 'fill', source: 'mask', paint: {'fill-color': '#e7eae6', 'fill-opacity': 0.92}});
    map.addSource('border', {type: 'geojson', data: "{{ url_for('offmap.border_geojson') }}"});
    map.addLayer({id: 'lebanon-border', type: 'line', source: 'border', paint: {'line-color': '#a8703a', 'line-width': 1.6, 'line-opacity': 0.8}});
    map.addSource('cazas', {type: 'geojson', data: "{{ url_for('offmap.cazas_geojson') }}"});
    map.addLayer({id: 'caza-lines', type: 'line', source: 'cazas',
      paint: {'line-color': '#7c8790', 'line-width': D.have_map ? 0.6 : 0.9, 'line-opacity': D.have_map ? 0.5 : 0.9}});
    map.addSource('incidents', {type: 'geojson', data: points});
    // Exact positions solid; approximate (caza-level) hollow, in the type colour.
    map.addLayer({id: 'incidents', type: 'circle', source: 'incidents', paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 5.5, 13, 9],
      'circle-color': ['case', ['get', 'exact'], ['get', 'fill'], '#ffffff'],
      'circle-stroke-color': ['case', ['get', 'exact'], '#ffffff', ['get', 'fill']],
      'circle-stroke-width': ['case', ['get', 'exact'], 2, 3]}});

    const open = id => {
      const i = byId[id]; if (!i) return;
      new maplibregl.Popup({maxWidth: '320px'}).setLngLat([i.lon, i.lat]).setDOMContent(popupNode(i)).addTo(map);
    };
    window.sirensOpenIncident = open;
    map.on('click', 'incidents', e => open(e.features[0].properties.id));
    map.on('mouseenter', 'incidents', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'incidents', () => { map.getCanvas().style.cursor = ''; });
    document.querySelectorAll('.inc').forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('.inc.on').forEach(x => x.classList.remove('on')); b.classList.add('on');
      const i = byId[b.dataset.id]; map.flyTo({center: [i.lon, i.lat], zoom: Math.max(map.getZoom(), D.have_map ? 11 : 9.5)}); open(i.id);
    }));
    // Filters: search, caza, exact only, types. The list and the map follow the same choice.
    const off = new Set();
    const q = document.getElementById('q'), cz = document.getElementById('caza'), ex = document.getElementById('exact');
    const count = document.getElementById('count'), nomatch = document.getElementById('nomatch');
    const applyFilters = () => {
      const words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
      const keep = D.incidents.filter(i => !off.has(i.type) && (!cz.value || i.caza === cz.value) && (!ex.checked || i.exact) &&
        words.every(w => [i.id, i.loc, i.street, i.snip, i.typelabel].join(' ').toLowerCase().includes(w)));
      const ids = new Set(keep.map(i => i.id));
      document.querySelectorAll('.inc').forEach(b => { b.hidden = !ids.has(b.dataset.id); });
      map.setFilter('incidents', ['in', ['get', 'id'], ['literal', [...ids]]]);
      count.textContent = keep.length + ' of ' + D.incidents.length + ' shown';
      nomatch.hidden = keep.length > 0 || !D.incidents.length;
    };
    q.addEventListener('input', applyFilters); cz.addEventListener('change', applyFilters); ex.addEventListener('change', applyFilters);
    document.querySelectorAll('.type').forEach(b => b.addEventListener('click', () => {
      const on = b.getAttribute('aria-pressed') === 'true';
      b.setAttribute('aria-pressed', on ? 'false' : 'true');
      on ? off.add(b.dataset.type) : off.delete(b.dataset.type);
      applyFilters();
    }));

    // Road name / number on hover.
    const roadLayers = map.getStyle().layers.filter(l => l['source-layer'] === 'roads' && l.type === 'line').map(l => l.id);
    if (roadLayers.length) {
    const tip = document.createElement('div'); tip.className = 'tip'; tip.setAttribute('role', 'tooltip');
    document.getElementById('map').appendChild(tip);
    map.on('mousemove', e => {
      if (map.queryRenderedFeatures(e.point, {layers: ['incidents']}).length) { tip.style.display = 'none'; return; }
      const f = map.queryRenderedFeatures([[e.point.x - 4, e.point.y - 4], [e.point.x + 4, e.point.y + 4]], {layers: roadLayers})
        .find(f => f.properties.name || f.properties.ref || f.properties['name:en']);
      if (!f) { tip.style.display = 'none'; return; }
      const p = f.properties, names = [];
      [p['name:en'], p.name, p['name:ar']].forEach(n => { if (n && !names.includes(n)) names.push(n); });
      tip.replaceChildren();
      names.forEach(n => { const d = document.createElement('div'); d.textContent = n; d.dir = 'auto'; tip.appendChild(d); });
      if (p.ref) { const r = document.createElement('div'); r.className = 'ref'; r.textContent = 'Road ' + p.ref; tip.appendChild(r); }
      tip.style.left = (e.point.x + 14) + 'px'; tip.style.top = (e.point.y + 14) + 'px'; tip.style.display = 'block';
    });
    map.on('mouseout', () => { tip.style.display = 'none'; });
    }
    // ---- MGRS grid, live readout and click-to-copy ----
    const G = window.SirensMGRS;
    map.addSource('mgrs', {type: 'geojson', data: {type: 'FeatureCollection', features: []}});
    map.addLayer({id: 'mgrs-lines', type: 'line', source: 'mgrs', filter: ['==', ['geometry-type'], 'LineString'],
      paint: {'line-color': '#3a4652', 'line-opacity': ['case', ['get', 'major'], 0.5, 0.25], 'line-width': ['case', ['get', 'major'], 1.2, 0.7]}});
    map.addLayer({id: 'mgrs-line-labels', type: 'symbol', source: 'mgrs', filter: ['all', ['==', ['geometry-type'], 'LineString'], ['!=', ['get', 'label'], '']],
      layout: {'symbol-placement': 'line', 'symbol-spacing': 320, 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 11},
      paint: {'text-color': '#3a4652', 'text-halo-color': '#ffffff', 'text-halo-width': 1.4}});
    map.addLayer({id: 'mgrs-squares', type: 'symbol', source: 'mgrs', filter: ['has', 'square'],
      layout: {'text-field': ['get', 'square'], 'text-font': ['Noto Sans Medium'], 'text-size': 14, 'text-allow-overlap': false},
      paint: {'text-color': '#16202b', 'text-opacity': 0.55, 'text-halo-color': '#ffffff', 'text-halo-width': 1.6}});
    map.addSource('seam', {type: 'geojson', data: {type: 'Feature', properties: {label: 'UTM zone 36S | 37S (36°E)'},
      geometry: {type: 'LineString', coordinates: [[36, y0 - 0.2], [36, y1 + 0.2]]}}});
    map.addLayer({id: 'zone-seam', type: 'line', source: 'seam', paint: {'line-color': '#a8703a', 'line-width': 1.4, 'line-opacity': 0.7}});
    map.addLayer({id: 'zone-seam-label', type: 'symbol', source: 'seam', layout: {'symbol-placement': 'line', 'symbol-spacing': 600,
      'text-field': ['get', 'label'], 'text-font': ['Noto Sans Medium'], 'text-size': 11}, paint: {'text-color': '#7a4e12', 'text-halo-color': '#fff', 'text-halo-width': 1.6}});
    ['incidents'].forEach(id => map.moveLayer(id));      // markers stay on top of the grid

    const spacing = z => z < 9 ? 100000 : z < 12 ? 10000 : 1000;
    const refreshGrid = () => {
      const b = map.getBounds();
      const box = [Math.max(b.getWest(), x0 - padX), Math.max(b.getSouth(), y0 - padY), Math.min(b.getEast(), x1 + padX), Math.min(b.getNorth(), y1 + padY)];
      map.getSource('mgrs').setData(G.gridFeatures(box, spacing(map.getZoom()), window.mgrs));
      window.sirensGridSpacing = spacing(map.getZoom());
    };
    map.on('moveend', refreshGrid); refreshGrid();

    const ro = document.createElement('div'); ro.className = 'readout'; ro.setAttribute('aria-live', 'polite');
    const idle = 'Move over the map for an MGRS reference';
    ro.textContent = idle; document.getElementById('map').appendChild(ro);
    const refAt = ll => G.format(window.mgrs.forward([ll.lng, ll.lat], 3));
    let copiedUntil = 0;
    map.on('mousemove', e => {
      if (Date.now() < copiedUntil) return;
      ro.className = 'readout'; ro.replaceChildren('MGRS ', Object.assign(document.createElement('b'), {textContent: refAt(e.lngLat)}), ' · click to copy');
    });
    map.getCanvas().addEventListener('mouseleave', () => { if (Date.now() >= copiedUntil) { ro.className = 'readout'; ro.textContent = idle; } });
    const copy = copyText;
    map.on('click', async e => {
      if (map.queryRenderedFeatures(e.point, {layers: ['incidents']}).length) return;   // a marker opens its popup instead
      const ref = refAt(e.lngLat), ok = await copy(ref);
      copiedUntil = Date.now() + 1800; ro.className = 'readout copied';
      ro.replaceChildren(ok ? 'Copied ' : 'Could not copy ', Object.assign(document.createElement('b'), {textContent: ref}));
      window.sirensLastCopied = ok ? ref : null;
    });
    window.sirensMapReady = true;
  });
  }
}
</script>
</body></html>
"""
