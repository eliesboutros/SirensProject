// "File a new report": section progress, map pin <-> MGRS, photo drop zone.
// Everything is local: the map uses the project's own files.
const $ = (id) => document.getElementById(id);
const form = document.getElementById('rp-form');

// ---------------------------------------------------------------- progress
const steps = {
  where: () => ['caza', 'street', 'mgrs', 'date'].some((id) => ($(id)?.value || '').trim()),
  what: () => ($('narrative')?.value || '').trim().length > 0,
  details: () => !!form.querySelector('input[name="munition"]:checked:not([value=""])') ||
    !!form.querySelector('input[name="item_color"]:checked:not([value=""])') ||
    !!form.querySelector('input[name="condition"]:checked') || ($('item_color_other')?.value || '').trim(),
  photo: () => ($('photo_file')?.files?.length || 0) > 0 || !!form.querySelector('input[name="photo"]'),
};
function refresh() {
  for (const [k, done] of Object.entries(steps)) {
    const a = document.querySelector(`.steps a[data-step="${k}"]`);
    if (a) a.classList.toggle('done', !!done());
  }
}
form.addEventListener('input', refresh);
form.addEventListener('change', refresh);
refresh();
const links = [...document.querySelectorAll('.steps a')];
const watch = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    links.forEach((a) => a.classList.toggle('here', a.getAttribute('href') === '#' + e.target.id));
  }
}, {rootMargin: '-35% 0px -55% 0px'});
document.querySelectorAll('.sec, .results').forEach((s) => watch.observe(s));

// ---------------------------------------------------------------- map pin
const mapEl = $('pickmap'), mgrsIn = $('mgrs'), latIn = $('lat'), lonIn = $('lon');
const note = $('pick-note'), clearBtn = $('pick-clear'), cazaSel = $('caza');
const fmt = (r) => r.replace(/^(\d{1,2}[A-Z])([A-Z]{2})(\d+)$/, (_, a, b, d) =>
  `${a} ${b} ${d.slice(0, d.length / 2)} ${d.slice(d.length / 2)}`);
function say(text, kind) { note.textContent = text; note.className = 'pick-note' + (kind ? ' ' + kind : ''); }

let map = null, marker = null, maplibregl = null, streets = false;
function place(lon, lat, {fromGrid = false, fly = true} = {}) {
  latIn.value = lat.toFixed(6); lonIn.value = lon.toFixed(6);
  if (!fromGrid) mgrsIn.value = fmt(window.mgrs.forward([lon, lat], 3));
  clearBtn.hidden = false;
  if (map) {
    if (!marker) {
      const el = document.createElement('div'); el.className = 'pin';
      marker = new maplibregl.Marker({element: el, anchor: 'bottom', draggable: true}).setLngLat([lon, lat]).addTo(map);
      marker.on('dragend', () => { const p = marker.getLngLat(); place(p.lng, p.lat, {fly: false}); });
    } else marker.setLngLat([lon, lat]);
    // Fill the caza from the outline under the pin (once the pin is in view).
    if (fly) { map.once('moveend', () => setCaza(lon, lat)); map.easeTo({center: [lon, lat], zoom: Math.max(map.getZoom(), streets ? 11 : 9)}); }
    else setCaza(lon, lat);
  }
  refresh();
}
function setCaza(lon, lat) {
  {
    const pt = map.project([lon, lat]);
    const hit = map.queryRenderedFeatures(pt, {layers: ['caza-fill']})[0];
    if (hit && cazaSel) {
      const name = hit.properties.name;
      if ([...cazaSel.options].some((o) => o.value === name)) {
        const changed = cazaSel.value !== name;
        cazaSel.value = name;
        say(changed ? `Pin placed. Caza set to ${name}.` : 'Pin placed.', 'ok');
      } else say('Pin placed.', 'ok');
    } else say('Pin placed, but it is outside Lebanon. Check the grid reference.', 'bad');
  }
}
function clearPin() {
  latIn.value = lonIn.value = mgrsIn.value = '';
  if (marker) { marker.remove(); marker = null; }
  clearBtn.hidden = true;
  say('Click the map to place the report, or type a grid reference.');
  refresh();
}
clearBtn.addEventListener('click', clearPin);
mgrsIn.addEventListener('change', () => {
  const v = mgrsIn.value.trim().toUpperCase().replace(/\s+/g, '');
  if (!v) { clearPin(); return; }
  try {
    const [lon, lat] = window.mgrs.toPoint(v);
    if (!isFinite(lon) || !isFinite(lat)) throw new Error('bad');
    mgrsIn.value = fmt(v);
    place(lon, lat, {fromGrid: true});
  } catch (e) {
    say('That grid reference is not valid. Write it like 36S YB 049 833.', 'bad');
  }
});

async function startMap() {
  try {
    maplibregl = await import('/static/vendor/maplibre-gl/maplibre-gl.mjs');
  } catch (e) { mapEl.hidden = true; return; }
  streets = false;
  let style = {version: 8, sources: {}, layers: [{id: 'bg', type: 'background', paint: {'background-color': '#eef1ee'}}]};
  if (mapEl.dataset.haveMap === '1') {
    try {
      const protocol = new pmtiles.Protocol();
      maplibregl.addProtocol('pmtiles', protocol.tile);
      style = await (await fetch(mapEl.dataset.style)).json();
      style.sources.protomaps.url = 'pmtiles://' + location.origin + mapEl.dataset.tiles;
      streets = true;
    } catch (e) { /* fall back to caza outlines only */ }
  }
  map = new maplibregl.Map({container: mapEl, style, bounds: [[35.1, 33.05], [36.62, 34.69]],
    fitBoundsOptions: {padding: 10}, minZoom: 6.5, maxZoom: 16, dragRotate: false,
    pitchWithRotate: false, attributionControl: {compact: true}});
  map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-right');
  map.setMaxZoom(streets ? 16 : 10.5);
  if (!streets) {
    const n = document.createElement('div'); n.className = 'pick-nomap';
    n.textContent = 'Street map not installed: district outlines only';
    mapEl.appendChild(n);
  }
  map.on('load', () => {
    map.addSource('cazas', {type: 'geojson', data: mapEl.dataset.cazas});
    map.addLayer({id: 'caza-fill', type: 'fill', source: 'cazas',
      paint: {'fill-color': '#b5761f', 'fill-opacity': mapEl.dataset.haveMap === '1' ? 0.02 : 0.06}});
    map.addLayer({id: 'caza-line', type: 'line', source: 'cazas',
      paint: {'line-color': '#7c8790', 'line-width': 0.8}});
    map.on('click', (e) => place(e.lngLat.lng, e.lngLat.lat, {fly: false}));
    map.once('idle', () => {
      if (latIn.value && lonIn.value) place(+lonIn.value, +latIn.value);
      else if (mgrsIn.value) mgrsIn.dispatchEvent(new Event('change'));
    });
  });
}
if (mapEl) startMap();

// ---------------------------------------------------------------- photo
const drop = $('drop'), file = $('photo_file'), dropClear = $('drop-clear');
const MAX = 8 * 1024 * 1024;
function showFile() {
  const f = file.files[0], err = $('e-photo_file');
  err.textContent = '';
  drop.querySelector('.drop-empty').hidden = !!f;
  drop.querySelector('.drop-full').hidden = !f;
  dropClear.hidden = !f;
  if (!f) return refresh();
  if (f.size > MAX) {
    err.textContent = `This photo is ${(f.size / 1048576).toFixed(1)} MB; the limit is 8 MB. Choose a smaller one.`;
    file.value = ''; return showFile();
  }
  $('drop-img').src = URL.createObjectURL(f);
  $('drop-name').textContent = `${f.name}, ${(f.size / 1048576).toFixed(1)} MB`;
  refresh();
}
file.addEventListener('change', showFile);
['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, () => drop.classList.remove('over')));
drop.addEventListener('drop', (e) => {
  e.preventDefault();
  if (e.dataTransfer.files.length) { file.files = e.dataTransfer.files; showFile(); }
});
document.addEventListener('paste', (e) => {
  const img = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith('image/'));
  if (!img || document.activeElement === $('narrative')) return;
  const dt = new DataTransfer(); dt.items.add(img); file.files = dt.files; showFile();
});
dropClear.addEventListener('click', () => { file.value = ''; showFile(); });
