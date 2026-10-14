// Builds static/map/style.json (the offline street-map style) from the
// Protomaps basemap style package. Build-time only; the app never runs this.
//
//   cd <some temp dir> && npm i @protomaps/basemaps@5.7.2
//   NODE_PATH=<temp dir>/node_modules node scripts/map/build_style.mjs
//
// Changes from the stock "light" flavour, so the style needs no sprite and no
// glyph server (everything is served from this repo, no network):
//   - layers that draw icons (one-way arrows, road shields, POIs) are dropped;
//     town labels keep their text without the dot icon;
//   - labels are drawn from local Noto Sans / Noto Sans Arabic files through
//     MapLibre's "font-faces" (no "glyphs" URL); Arabic is shaped by the browser.
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { layers, namedFlavor } = require('@protomaps/basemaps');

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, '..', '..', 'static', 'map', 'style.json');

const DROP = new Set(['roads_oneway', 'roads_shields', 'pois']);
const all = layers('protomaps', namedFlavor('light'), { lang: 'en' }).filter(l => !DROP.has(l.id));
for (const l of all) {
  if (l.layout) for (const k of Object.keys(l.layout)) if (k.startsWith('icon-')) delete l.layout[k];
}

const F = '/static/map/fonts/';
const latin = (w, s = 'normal') => [
  { url: `${F}noto-sans-latin-${w}-${s}.woff2`, 'unicode-range': ['U+0000-00FF', 'U+0131', 'U+0152-0153', 'U+02BB-02BC', 'U+02C6', 'U+02DA', 'U+02DC', 'U+2000-206F', 'U+20AC', 'U+2122', 'U+2191', 'U+2193', 'U+2212', 'U+2215', 'U+FEFF', 'U+FFFD'] },
  { url: `${F}noto-sans-latin-ext-${w}-${s}.woff2`, 'unicode-range': ['U+0100-02AF', 'U+0304', 'U+0308', 'U+0329', 'U+1E00-1E9F', 'U+1EF2-1EFF', 'U+2020', 'U+20A0-20AB', 'U+20AD-20C0', 'U+2113', 'U+2C60-2C7F', 'U+A720-A7FF'] },
];
const arabic = w => ({ url: `${F}noto-sans-arabic-arabic-${w}-normal.woff2`, 'unicode-range': ['U+0600-06FF', 'U+0750-077F', 'U+0870-088E', 'U+0890-0891', 'U+0897-08E1', 'U+08E3-08FF', 'U+200C-200E', 'U+2010-2011', 'U+204F', 'U+2E41', 'U+FB50-FDFF', 'U+FE70-FE74', 'U+FE76-FEFC'] });

const style = {
  version: 8,
  name: 'Sirens offline street map (Protomaps light, OpenStreetMap data)',
  sources: {
    protomaps: {
      type: 'vector',
      url: 'pmtiles://MAP_URL',              // replaced in the browser with this server's map file
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  'font-faces': {
    'Noto Sans Regular': [...latin('400'), arabic('400')],
    'Noto Sans Medium': [...latin('600'), arabic('600')],
    'Noto Sans Italic': [...latin('400', 'italic'), arabic('400')],
  },
  layers: all,
};
writeFileSync(out, JSON.stringify(style, null, 1) + '\n');
console.log(`wrote ${out}: ${all.length} layers`);
