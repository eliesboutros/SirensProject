"""Write a small SYNTHETIC PMTiles map file for tests and development.

This is NOT a real street map. It lets the /map page, offline serving (HTTP
Range), road hover and the Lebanon mask be tested without the real
OpenStreetMap file, which is downloaded or built on a laptop (see
scripts/map/get_map.sh and scripts/map/build_map.sh).

Contents, using the same layer names as the Protomaps basemap tiles the style
expects: "earth" (Lebanon's outline, from data/regions.json), "places" (one
point per caza, named after it) and "roads" (straight TEST lines between caza
centres, named "Test road N" / "طريق تجريبي N" with ref "TN"). Zooms 6-11.

    python scripts/map/make_test_map.py out.pmtiles

Needs the dev requirements (requirements-dev.txt): pmtiles, mapbox-vector-tile.
"""
from __future__ import annotations

import gzip
import json
import math
import pathlib
import sys

import mapbox_vector_tile
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from map_bp import lebanon_border, caza_centres  # noqa: E402

EXTENT = 4096
MINZOOM, MAXZOOM = 6, 11
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def _merc(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _local(pts, z, tx, ty):
    out = []
    for lon, lat in pts:
        x, y = _merc(lon, lat, z)
        out.append((round((x - tx) * EXTENT), round((y - ty) * EXTENT)))
    return out


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _ar(n):
    return "".join(ARABIC_DIGITS[int(d)] for d in str(n))


def build_features():
    border = lebanon_border()
    centres = caza_centres()                         # [(name, lon, lat)]
    names = sorted(centres)
    roads = []
    # chain the caza centres south->north, plus a coastal test line
    ordered = sorted(centres.items(), key=lambda kv: kv[1][1])
    for i, ((a, pa), (b, pb)) in enumerate(zip(ordered, ordered[1:]), start=1):
        roads.append({"pts": [pa, pb], "props": {"kind": "major_road" if i % 3 else "highway",
                      "name": f"طريق تجريبي {_ar(i)}", "name:en": f"Test road {i}",
                      "name:ar": f"طريق تجريبي {_ar(i)}", "ref": f"T{i}", "min_zoom": 6}})
    places = [{"pt": centres[n], "props": {"kind": "locality", "name": n, "min_zoom": 6,
               "population_rank": 10}} for n in names]
    return border, roads, places


def write(path):
    border, roads, places = build_features()
    bx0, by0, bx1, by1 = _bbox(border)
    path = pathlib.Path(path)
    tiles = {}
    for z in range(MINZOOM, MAXZOOM + 1):
        x0, y0 = _merc(bx0, by1, z)
        x1, y1 = _merc(bx1, by0, z)
        for tx in range(int(x0), int(x1) + 1):
            for ty in range(int(y0), int(y1) + 1):
                layers = [
                    {"name": "earth", "features": [{"geometry": {"type": "Polygon",
                     "coordinates": [_local(border, z, tx, ty)]}, "properties": {"kind": "earth"}}]},
                    {"name": "roads", "features": [{"geometry": {"type": "LineString",
                     "coordinates": _local(r["pts"], z, tx, ty)}, "properties": r["props"]} for r in roads]},
                    {"name": "places", "features": [{"geometry": {"type": "Point",
                     "coordinates": _local([p["pt"]], z, tx, ty)[0]}, "properties": p["props"]} for p in places]},
                ]
                data = mapbox_vector_tile.encode(layers, default_options={"y_coord_down": True,
                                                                          "extents": EXTENT})
                tiles[zxy_to_tileid(z, tx, ty)] = gzip.compress(data)
    with open(path, "wb") as fh:
        w = Writer(fh)
        for tid in sorted(tiles):              # tile-id order = a "clustered" archive, like real builds
            w.write_tile(tid, tiles[tid])
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        w.finalize(
            {"tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
             "min_zoom": MINZOOM, "max_zoom": MAXZOOM,
             "min_lon_e7": int(bx0 * 1e7), "min_lat_e7": int(by0 * 1e7),
             "max_lon_e7": int(bx1 * 1e7), "max_lat_e7": int(by1 * 1e7),
             "center_zoom": 8, "center_lon_e7": int(cx * 1e7), "center_lat_e7": int(cy * 1e7)},
            {"name": "SIRENS SYNTHETIC TEST MAP (not real roads)",
             "attribution": "Test data generated from data/regions.json",
             "vector_layers": [{"id": "earth", "fields": {}}, {"id": "roads", "fields": {}},
                               {"id": "places", "fields": {}}]})
    return path


if __name__ == "__main__":
    out = write(sys.argv[1] if len(sys.argv) > 1 else "test_map.pmtiles")
    print(f"wrote {out} ({out.stat().st_size} bytes) — synthetic test data, not a real map")
