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
<link rel="stylesheet" href="{{ url_for('static', filename='vendor/maplibre-gl/maplibre-gl.css') }}">
<style>
  :root{--ink:#16202b;--soft:#3a4652;--weak:#7a8791;--line:#e2e6e3;--line2:#eef0ee;--surface:#f4f6f3;
    --sig:#a8703a;--sig-soft:#f0e6d4;--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  *{box-sizing:border-box}
  html,body{height:100%}
  /* The map fills exactly the viewport under the header; only the incident list scrolls. */
  body{margin:0;background:var(--surface);color:var(--ink);font-family:var(--sans);line-height:1.5;
       display:flex;flex-direction:column;height:100vh;overflow:hidden}
  .bar{display:flex;align-items:center;gap:20px;flex-wrap:wrap;padding:18px 32px;background:var(--ink);
       color:#eef2f5;border-bottom:3px solid var(--sig)}
  .brand{font-family:var(--mono);font-weight:600;letter-spacing:.16em;text-transform:uppercase;font-size:15px}
  .brand small{display:block;letter-spacing:.06em;font-size:10px;color:#9fb0bd;font-weight:400;margin-top:2px}
  .stage{flex:1;display:grid;grid-template-columns:minmax(0,1fr) 330px;grid-template-rows:minmax(0,1fr);min-height:0}
  @media(max-width:900px){body{height:auto;overflow:visible}
    .stage{grid-template-columns:1fr;grid-template-rows:62vh auto}}
  #map{position:relative;min-height:420px;background:#e9ece8}
  .side{background:#fff;border-left:1px solid var(--line);overflow-y:auto;padding:16px 18px 24px}
  @media(max-width:900px){.side{border-left:0;border-top:1px solid var(--line)}}
  .side h2{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--soft);
           margin:6px 0 10px;font-weight:600}
  .note{font-size:12.5px;color:var(--soft);background:var(--line2);border-radius:6px;padding:9px 11px;margin:0 0 14px}
  .legend{display:flex;flex-wrap:wrap;gap:6px 12px;margin:0 0 14px;font-size:12.5px;color:var(--soft)}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .dot{width:10px;height:10px;border-radius:50%;display:inline-block;box-shadow:0 0 0 2px #fff,0 0 0 3px rgba(22,32,43,.15)}
  .inc{display:block;width:100%;text-align:left;background:#fff;border:1px solid var(--line);border-radius:8px;
       padding:9px 11px;margin:0 0 8px;cursor:pointer;font:inherit;color:inherit}
  .inc:hover,.inc:focus-visible{border-color:var(--sig);outline:none}
  .inc b{font-family:var(--mono);font-size:12.5px}
  .inc small{display:block;color:var(--weak);font-size:12px}
  .missing{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:24px}
  .missing .card{max-width:520px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:22px 24px;
       box-shadow:0 1px 2px rgba(22,32,43,.04),0 4px 16px rgba(22,32,43,.06)}
  .missing h1{font-size:17px;margin:0 0 8px}
  .missing code{font-family:var(--mono);background:var(--line2);padding:2px 6px;border-radius:4px}
  .tip{position:absolute;z-index:5;pointer-events:none;background:#fff;border:1px solid var(--line);border-radius:7px;
       padding:6px 9px;font-size:12.5px;box-shadow:0 2px 6px rgba(22,32,43,.1),0 8px 20px rgba(22,32,43,.12);display:none;
       max-width:280px}
  .tip .ref{font-family:var(--mono);font-size:11.5px;color:var(--soft)}
  .maplibregl-popup-content{font-family:var(--sans);font-size:13px;border-radius:9px;padding:12px 14px;max-width:300px}
  .pop h3{font-family:var(--mono);font-size:13px;margin:0 0 4px}
  .pop .meta{color:var(--weak);font-size:12px;margin:0 0 6px}
  .pop .row{margin:2px 0}
  .pop .approx{font-size:11.5px;color:#7a4e12;background:var(--sig-soft);border-radius:4px;padding:2px 6px;display:inline-block;margin-top:4px}
  .pop .snip{color:var(--soft);font-size:12.5px;margin-top:6px}
  .readout{position:absolute;z-index:4;left:50%;bottom:12px;transform:translateX(-50%);background:rgba(255,255,255,.95);
       border:1px solid var(--line);border-radius:999px;padding:6px 14px;font-size:12.5px;color:var(--soft);
       box-shadow:0 2px 8px rgba(22,32,43,.12);white-space:nowrap}
  .readout b{font-family:var(--mono);color:var(--ink);font-weight:600;letter-spacing:.02em}
  .readout.copied{border-color:#c9dcc6;background:#e7efe5;color:#3d6b45}
</style>
</head><body>
<div class="bar"><div class="brand">Sirens<small>incident map · Lebanon (offline street map)</small></div>{{ sirens_menu('map') }}</div>
<div class="stage">
  <div id="map" role="region" aria-label="Street map of Lebanon with incident markers">
    {% if not have_map %}
    <div class="missing"><div class="card" role="status">
      <h1>Offline map not installed — run <code>bash setup.sh</code></h1>
      <p>The street map is one file, <code>data/map/lebanon.pmtiles</code>, downloaded once by <code>setup.sh</code>
        (it is not stored in git). After that the map works with no internet. The incidents are listed on the right.</p>
    </div></div>
    {% endif %}
  </div>
  <aside class="side">
    <h2>Incidents on the map ({{ incidents|length }})</h2>
    <p class="note">Positions follow the record: a filed grid reference gives an exact point; other reports are placed
      at their caza (district) and spread around its centre, so the marker is approximate.</p>
    {% if unplaced %}<p class="note">{{ unplaced }} report(s) have no known caza or grid reference, so they are not on the map.</p>{% endif %}
    {% if legend %}<div class="legend">{% for t in legend %}<span><i class="dot" style="background:{{ t.color }}"></i>{{ t.label }} ({{ t.count }})</span>{% endfor %}</div>{% endif %}
    {% for i in incidents %}
    <button type="button" class="inc" data-id="{{ i.id }}"><b>{{ i.id }}</b> · {{ i.typelabel }}
      <small>{{ i.loc or 'no location' }} · {{ i.date or 'no date' }} · {{ 'exact grid' if i.exact else 'approx. (caza level)' }}</small></button>
    {% else %}<p class="note">No incidents could be placed. Load the demo data or file a report with a caza.</p>{% endfor %}
    <p class="note"><strong>MGRS grid</strong> (6-digit, 100 m): 100 km squares when zoomed out, 10 km lines at
      district zoom, 1 km lines up close. Move over the map to read a reference; click to copy it.
      Lebanon spans zones <b>36S</b> and <b>37S</b>, which meet at <b>36&deg;E</b> in the Bekaa: the grid jumps
      at that line, which is correct.</p>
    <p class="note" style="margin-top:14px">Map data {{ attribution }}. Street map shown for orientation only.</p>
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
  const add = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; n.textContent = text; el.appendChild(n); return n; };
  add('h3', '', i.id + ' · ' + i.typelabel);
  add('div', 'meta', (i.date || 'no date') + ' · ' + (i.loc || 'no location'));
  if (i.street) add('div', 'row', 'Place: ' + i.street);
  if (i.item_color) add('div', 'row', 'Colour / markings: ' + i.item_color);
  if (i.condition && i.condition.length) add('div', 'row', 'Condition: ' + i.condition.join(', '));
  if (i.grid) add('div', 'row', 'Grid: ' + i.grid);
  if (i.mgrs) add('div', 'row', 'MGRS: ' + i.mgrs + (i.exact ? '' : ' (approx., caza centre)'));
  add('span', 'approx', i.exact ? 'Exact: from the filed grid reference' : 'Approx. — placed at caza level');
  if (i.snip) add('div', 'snip', i.snip);
  return el;
}

const points = {type: 'FeatureCollection', features: D.incidents.map(i => ({
  type: 'Feature', id: i.id, properties: {id: i.id, fill: i.fill},
  geometry: {type: 'Point', coordinates: [i.lon, i.lat]}}))};
const byId = Object.fromEntries(D.incidents.map(i => [i.id, i]));

if (D.have_map) {
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
  style.sources.protomaps.url = 'pmtiles://' + location.origin + "{{ url_for('offmap.pmtiles_file') }}";
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
    map.addSource('incidents', {type: 'geojson', data: points});
    map.addLayer({id: 'incidents', type: 'circle', source: 'incidents', paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 5, 13, 8], 'circle-color': ['get', 'fill'],
      'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2}});

    const open = id => {
      const i = byId[id]; if (!i) return;
      new maplibregl.Popup({maxWidth: '320px'}).setLngLat([i.lon, i.lat]).setDOMContent(popupNode(i)).addTo(map);
    };
    window.sirensOpenIncident = open;
    map.on('click', 'incidents', e => open(e.features[0].properties.id));
    map.on('mouseenter', 'incidents', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'incidents', () => { map.getCanvas().style.cursor = ''; });
    document.querySelectorAll('.inc').forEach(b => b.addEventListener('click', () => {
      const i = byId[b.dataset.id]; map.flyTo({center: [i.lon, i.lat], zoom: Math.max(map.getZoom(), 11)}); open(i.id);
    }));

    // Road name / number on hover.
    const roadLayers = map.getStyle().layers.filter(l => l['source-layer'] === 'roads' && l.type === 'line').map(l => l.id);
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
    const copy = async text => {
      try { await navigator.clipboard.writeText(text); return true; } catch (err) {
        const t = Object.assign(document.createElement('textarea'), {value: text}); document.body.appendChild(t); t.select();
        const ok = document.execCommand('copy'); t.remove(); return ok; }
    };
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
