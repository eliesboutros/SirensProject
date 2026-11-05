"""Which caza a GPS point falls in, from the bundled data/regions.json.

Civilian reports arrive with a phone's GPS position, not a place name, so the
internal server needs the caza to decide which military users may see them.
Pure Python ray casting over the caza outlines; no extra packages.
"""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache

REGIONS_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "regions.json"


@lru_cache(maxsize=1)
def _features():
    try:
        data = json.loads(REGIONS_FILE.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for f in data.get("features", []):
        geom = f.get("geometry") or {}
        polys = geom.get("coordinates", [])
        if geom.get("type") == "Polygon":
            polys = [polys]
        out.append((f["properties"]["name"], polys, _bbox(polys)))
    return out


def _bbox(polys):
    xs = [x for poly in polys for ring in poly for x, _y in ring]
    ys = [y for poly in polys for ring in poly for _x, y in ring]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)


def _in_ring(lon, lat, ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polygon(lon, lat, poly) -> bool:
    # First ring is the outline, the rest are holes.
    return _in_ring(lon, lat, poly[0]) and not any(_in_ring(lon, lat, h) for h in poly[1:])


def names() -> list[str]:
    """Every caza name, once each, sorted."""
    return sorted({n for n, _p, _b in _features()})


def caza_at(lat: float, lon: float) -> str | None:
    """The caza containing the point, or None if it is outside Lebanon."""
    for name, polys, (x0, y0, x1, y1) in _features():
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        if any(_in_polygon(lon, lat, poly) for poly in polys):
            return name
    return None
