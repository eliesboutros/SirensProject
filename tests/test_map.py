"""Offline street map (/map): serving, Lebanon outline, markers, no network."""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_map_file(tmp_path_factory):
    pytest.importorskip("mapbox_vector_tile")
    pytest.importorskip("pmtiles")
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_test_map", ROOT / "scripts" / "map" / "make_test_map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.write(tmp_path_factory.mktemp("map") / "test.pmtiles")


@pytest.fixture
def with_map(client, test_map_file):
    import app as sirens_app
    sirens_app.app.config["SIRENS_MAP_FILE"] = str(test_map_file)
    yield client
    sirens_app.app.config.pop("SIRENS_MAP_FILE", None)


@pytest.fixture
def without_map(client, tmp_path):
    import app as sirens_app
    sirens_app.app.config["SIRENS_MAP_FILE"] = str(tmp_path / "absent.pmtiles")
    yield client
    sirens_app.app.config.pop("SIRENS_MAP_FILE", None)


def _data(html):
    return json.loads(re.search(r'<script id="map-data" type="application/json">(.*?)</script>', html, re.S).group(1))


def test_missing_map_file_says_so_and_still_lists_incidents(without_map):
    without_map.post("/seed")
    r = without_map.get("/map")
    html = r.data.decode()
    assert r.status_code == 200
    assert "Offline map not installed — run <code>bash setup.sh</code>" in html
    assert html.count('class="inc"') == 40
    assert without_map.get("/map/data/lebanon.pmtiles").status_code == 404


def test_map_page_with_file(with_map):
    with_map.post("/seed")
    html = with_map.get("/map").data.decode()
    assert "Offline map not installed" not in html
    d = _data(html)
    assert d["have_map"] and len(d["incidents"]) == 40
    assert "© OpenStreetMap contributors" in html
    assert "/static/vendor/maplibre-gl/maplibre-gl.mjs" in html and "/static/vendor/pmtiles/pmtiles.js" in html


def test_map_file_is_served_with_http_range(with_map, test_map_file):
    r = with_map.get("/map/data/lebanon.pmtiles", headers={"Range": "bytes=0-126"})
    assert r.status_code == 206
    assert r.headers["Content-Range"] == f"bytes 0-126/{test_map_file.stat().st_size}"
    assert r.data[:7] == b"PMTiles" and len(r.data) == 127


def test_lebanon_border_and_mask():
    import map_bp
    border = map_bp.lebanon_border()
    assert border[0] == border[-1] and len(border) > 500          # one closed ring
    area = abs(map_bp._area(border[:-1]))
    assert 0.9 < area < 1.1                                       # ~10,450 km2 ~ 1 square degree
    x0, y0, x1, y1 = map_bp.bounds()
    assert 35.0 < x0 < 35.2 and 36.5 < x1 < 36.7 and 33.0 < y0 < 33.1 and 34.6 < y1 < 34.8


def _inside(pt, ring):
    x, y, hit = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def test_every_caza_centre_is_inside_lebanon():
    import map_bp
    border = map_bp.lebanon_border()
    centres = map_bp.caza_centres()
    assert len(centres) >= 25
    assert all(_inside(c, border) for c in centres.values())


def test_mask_cuts_lebanon_out_of_the_world(client):
    g = client.get("/map/mask.geojson").get_json()["geometry"]
    assert g["type"] == "Polygon" and len(g["coordinates"]) == 2      # world ring + Lebanon hole


def test_markers_are_approx_unless_a_grid_was_filed(with_map):
    with_map.post("/seed")
    with_map.post("/analyse", data={"incident_id": "INC-077", "narrative": "Fabricated test report.",
                                    "action": "save", "grid_mode": "latlon", "lat": "33.2", "lon": "35.4"})
    d = _data(with_map.get("/map").data.decode())
    by = {i["id"]: i for i in d["incidents"]}
    assert by["INC-077"]["exact"] is True and (by["INC-077"]["lat"], by["INC-077"]["lon"]) == (33.2, 35.4)
    assert by["INC-001"]["exact"] is False and by["INC-001"]["caza"]
    x0, y0, x1, y1 = d["bounds"]
    assert all(x0 - 0.1 <= i["lon"] <= x1 + 0.1 and y0 - 0.1 <= i["lat"] <= y1 + 0.1 for i in d["incidents"])


def test_map_style_and_fonts_are_local_only():
    style = json.loads((ROOT / "static" / "map" / "style.json").read_text())
    assert "glyphs" not in style and "sprite" not in style         # nothing fetched from a glyph/sprite server
    assert style["sources"]["protomaps"]["url"] == "pmtiles://MAP_URL"
    assert "OpenStreetMap" in style["sources"]["protomaps"]["attribution"]
    urls = [f["url"] for faces in style["font-faces"].values() for f in faces]
    assert urls and all(u.startswith("/static/map/fonts/") for u in urls)
    assert all((ROOT / u.lstrip("/")).is_file() for u in urls)
    assert not any("icon-image" in (l.get("layout") or {}) for l in style["layers"])
    # the only http(s) text left in the style is the attribution link, which is never fetched
    style["sources"]["protomaps"].pop("attribution")
    assert not re.search(r"https?://", json.dumps(style))


def test_map_page_requests_only_this_server(with_map):
    html = with_map.get("/map").data.decode()
    for m in re.finditer(r'(?:src|href)="([^"]+)"|fetch\("([^"]+)"\)|import[^"]*"([^"]+)"', html):
        url = next(g for g in m.groups() if g)
        assert url.startswith("/") or url.startswith("#"), url
    assert "maplibregl.addProtocol('pmtiles'" in html
