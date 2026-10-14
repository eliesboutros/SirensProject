"""Latitude/longitude to UTM and MGRS (WGS84), pure Python, no dependencies.

Used for the MGRS reference in map popups. MGRS is given at 6 digits (100 m),
formatted like "36S YC 311 527". Lebanon spans UTM zones 36 and 37, which meet
at 36 degrees east (in the Bekaa); standard zones are used, so a reference
jumps from 36S to 37S across that line, which is correct.

UTM uses the Krueger series (accurate to well under a millimetre within a
zone); MGRS lettering is the standard WGS84 ("AA") scheme. Tested against the
independent pyproj and mgrs packages, including both sides of 36 E.
"""
from __future__ import annotations

import math

_A = 6378137.0                      # WGS84 semi-major axis (m)
_F = 1 / 298.257223563              # WGS84 flattening
_K0 = 0.9996
_N = _F / (2 - _F)
_AA = _A / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
_ALPHA = (
    _N / 2 - 2 * _N ** 2 / 3 + 5 * _N ** 3 / 16,
    13 * _N ** 2 / 48 - 3 * _N ** 3 / 5,
    61 * _N ** 3 / 240,
)
_BANDS = "CDEFGHJKLMNPQRSTUVWX"          # 8-degree latitude bands from 80S
_COLS = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")
_ROWS = "ABCDEFGHJKLMNPQRSTUV"


def utm_zone(lon: float) -> int:
    """Standard UTM zone number (Lebanon needs no Norway/Svalbard exceptions)."""
    return int((lon + 180) // 6) % 60 + 1


def to_utm(lat: float, lon: float, zone: int | None = None) -> tuple[int, str, float, float]:
    """(zone, band letter, easting m, northing m) for a WGS84 point."""
    if not -80 <= lat < 84:
        raise ValueError("MGRS/UTM covers latitudes 80S to 84N")
    zone = zone or utm_zone(lon)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    phi, lam = math.radians(lat), math.radians(lon) - lon0
    e = math.sqrt(_F * (2 - _F))
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi = math.atan2(t, math.cos(lam))
    eta = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    x = eta + sum(a * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, a in enumerate(_ALPHA, 1))
    y = xi + sum(a * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, a in enumerate(_ALPHA, 1))
    easting = 500000 + _K0 * _AA * x
    northing = _K0 * _AA * y + (10000000 if lat < 0 else 0)
    band = _BANDS[min(int((lat + 80) // 8), len(_BANDS) - 1)]
    return zone, band, easting, northing


def to_mgrs(lat: float, lon: float, digits: int = 6) -> str:
    """MGRS reference, e.g. "36S YC 311 527" (digits=6 means 100 m squares).

    Digits are truncated, as MGRS requires: the reference names the square the
    point lies in, not the nearest grid line."""
    if digits not in (2, 4, 6, 8, 10):
        raise ValueError("digits must be 2, 4, 6, 8 or 10")
    zone, band, e, n = to_utm(lat, lon)
    col = _COLS[(zone - 1) % 3][int(e // 100000) - 1]
    row = _ROWS[(int(n // 100000) + (5 if zone % 2 == 0 else 0)) % 20]
    half = digits // 2
    unit = 10 ** (5 - half)
    ee = int((e % 100000) // unit)
    nn = int((n % 100000) // unit)
    return f"{zone}{band} {col}{row} {ee:0{half}d} {nn:0{half}d}"
