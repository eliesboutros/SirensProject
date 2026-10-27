"""MGRS / UTM conversion checked against independent libraries (no hand-written answers).

References: the `mgrs` package (MGRS strings) and `pyproj` (UTM coordinates),
both test-only dependencies (requirements-dev.txt). Points cover Lebanon's
bounding box plus pairs just either side of the 36 E zone seam. The browser's
code (vendored mgrs library + static/map/mgrs_grid.js) is run under Node when
Node is available.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from linker.grid_ref import to_mgrs, to_utm

mgrs = pytest.importorskip("mgrs")
pyproj = pytest.importorskip("pyproj")

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAT0, LAT1, LON0, LON1 = 33.03, 34.72, 35.08, 36.65


def _points():
    pts = [(LAT0 + (LAT1 - LAT0) * i / 19, LON0 + (LON1 - LON0) * j / 19) for i in range(20) for j in range(20)]
    for k in range(18):                                     # both sides of the 36 E seam
        lat = LAT0 + (LAT1 - LAT0) * k / 17
        pts += [(lat, 35.9999), (lat, 35.99999), (lat, 36.0), (lat, 36.00001), (lat, 36.0001)]
    return [(round(a, 6), round(b, 6)) for a, b in pts]


POINTS = _points()


def test_mgrs_matches_the_mgrs_package_everywhere_in_lebanon():
    ref = mgrs.MGRS()
    bad = [(lat, lon, to_mgrs(lat, lon), ref.toMGRS(lat, lon, MGRSPrecision=3))
           for lat, lon in POINTS if to_mgrs(lat, lon).replace(" ", "") != ref.toMGRS(lat, lon, MGRSPrecision=3)]
    assert not bad, bad[:5]
    assert len(POINTS) > 450


def test_seam_uses_standard_zones():
    assert to_mgrs(34.0, 35.99999).startswith("36S ")
    assert to_mgrs(34.0, 36.0).startswith("37S ")
    ref = mgrs.MGRS()
    for lat in (33.1, 33.9, 34.6):
        assert to_mgrs(lat, 35.9999).replace(" ", "") == ref.toMGRS(lat, 35.9999, MGRSPrecision=3)
        assert to_mgrs(lat, 36.0001).replace(" ", "") == ref.toMGRS(lat, 36.0001, MGRSPrecision=3)


def test_utm_matches_pyproj_to_a_millimetre():
    worst = 0.0
    for lat, lon in POINTS:
        zone, band, e, n = to_utm(lat, lon)
        assert band == "S"
        t = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:326{zone}", always_xy=True)
        pe, pn = t.transform(lon, lat)
        worst = max(worst, abs(e - pe), abs(n - pn))
    assert worst < 0.001, worst


def test_format_is_six_digit_with_spaces():
    import re
    for lat, lon in POINTS[:50]:
        assert re.fullmatch(r"3[67]S [A-Z]{2} \d{3} \d{3}", to_mgrs(lat, lon))


def test_map_popups_carry_mgrs(client):
    import map_bp
    import re as _re
    client.post("/seed")
    html = client.get("/map").data.decode()
    d = json.loads(_re.search(r'<script id="map-data" type="application/json">(.*?)</script>', html, _re.S).group(1))
    by = {i["id"]: i for i in d["incidents"]}
    i = by["INC-008"]
    assert i["exact"] is False
    lon, lat = map_bp.caza_centres()[i["caza"]]
    assert i["mgrs"] == to_mgrs(lat, lon)                    # approx: names the caza centre
    assert "(approx., caza centre)" in html


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="Node is not installed")
def test_browser_code_matches_the_references():
    script = r"""
      const m = require(process.argv[1] + '/static/vendor/mgrs/mgrs.min.js');
      const G = require(process.argv[1] + '/static/map/mgrs_grid.js');
      const pts = JSON.parse(process.argv[2]);
      const fwd = pts.map(([lat, lon]) => m.forward([lon, lat], 3));
      const inv = pts.map(([lat, lon]) => { const z = G.zoneOf(lon); const [e, n] = G.lonLatToUtm(lon, lat, z); return [z, e, n, G.utmToLonLat(z, e, n)]; });
      const lines = G.gridFeatures([35.4, 33.2, 36.4, 33.7], 10000, m).features.filter(f => f.geometry.type === 'LineString');
      const lons = z => lines.filter(f => f.properties.zone === z).flatMap(f => f.geometry.coordinates.map(c => c[0]));
      console.log(JSON.stringify({fwd, inv, z36max: Math.max(...lons(36)), z37min: Math.min(...lons(37)), fmt: G.format('36SYC311527')}));
    """
    out = subprocess.run([NODE, "-e", script, str(ROOT), json.dumps(POINTS)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    ref = mgrs.MGRS()
    assert [s for s, (lat, lon) in zip(r["fwd"], POINTS) if s != ref.toMGRS(lat, lon, MGRSPrecision=3)] == []
    for (z, e, n, (lon2, lat2)), (lat, lon) in zip(r["inv"], POINTS):
        t = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:326{z}", always_xy=True)
        pe, pn = t.transform(lon, lat)
        assert abs(e - pe) < 0.01 and abs(n - pn) < 0.01            # grid helper forward
        assert abs(lon2 - lon) < 1e-7 and abs(lat2 - lat) < 1e-7      # and back (about 1 cm)
    assert r["z36max"] <= 36.0 + 1e-9 and r["z37min"] >= 36.0 - 1e-9    # each zone's grid stops at the seam
    assert r["fmt"] == "36S YC 311 527"
