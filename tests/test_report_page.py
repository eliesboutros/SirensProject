"""The redesigned report page: kept input, MGRS, highlights, merged links, saved page."""
import io
import json
import re

import pytest

from linker import store
from linker.grid_ref import from_mgrs, to_mgrs

TEXT = ("Fabricated test. On 3 November an IED was found buried by the roadside near Khiam, "
        "targeting a convoy. Pressure plate, main charge homemade explosive in a yellow jerrycan.")
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


def test_mgrs_reader_round_trips_and_explains_errors():
    lat, lon = from_mgrs("36S YB 049 833")
    assert to_mgrs(lat, lon) == "36S YB 049 833"
    assert from_mgrs("36syb049833") == (lat, lon)
    for bad, words in [("36S YB 04 833", "same number"), ("hello", "write the grid"),
                       ("36N YB 049 833", "band N")]:
        with pytest.raises(ValueError, match=words):
            from_mgrs(bad)


def test_analyse_keeps_everything_typed(client):
    client.post("/seed")
    html = client.post("/analyse", data={
        "action": "analyse", "incident_id": "INC-041", "narrative": TEXT, "street": "Khiam",
        "date": "2026-11-03", "mgrs": "36S YB 049 833", "munition": "ied",
        "item_color": "yellow", "item_color_other": "white stencil", "condition": ["buried", "intact"],
    }).data.decode()
    assert "homemade explosive in a yellow jerrycan.</textarea>" in html
    assert re.search(r'id="street"[^>]*value="Khiam"', html)
    assert re.search(r'id="mgrs"[^>]*value="36S YB 049 833"', html)
    assert re.search(r'name="munition" value="ied" checked', html)
    assert re.search(r'name="item_color" value="yellow" checked', html)
    assert re.search(r'name="condition" value="buried" checked', html) and \
           re.search(r'name="condition" value="intact" checked', html)
    # The caza is filled from the grid reference (36S YB 049 833 is in Sour).
    assert re.search(r'<option value="Sour" selected>', html)
    assert store.get_incident("INC-041") is None                 # not saved
    assert "Not saved yet" in html


def test_findings_are_plain_and_traced_to_the_text(client):
    client.post("/seed")
    html = client.post("/analyse", data={"action": "analyse", "narrative": TEXT}).data.decode()
    assert '<mark class="hl hl-device" title="Trigger: pressure plate">Pressure plate</mark>' in html
    assert "<dt>Main charge</dt><dd>homemade explosive</dd>" in html
    assert "trigger=pressure_plate" not in html                  # no code-style labels
    # One ranked list: each past report once, strongest first, with plain reasons.
    ids = re.findall(r'<span class="lk-id mono">(INC-\d+)</span>', html)
    assert ids and len(ids) == len(set(ids))
    assert "Shares</span> Trigger: pressure plate" in html
    assert html.count('<details class="cmp">') == len(ids)


def test_bad_grid_reference_is_refused_next_to_the_form(client):
    html = client.post("/analyse", data={"action": "save", "narrative": TEXT,
                                         "mgrs": "36S YB 04 833"}).data.decode()
    assert "Grid reference not understood" in html and store.count() == 0
    form = html[html.index('<form class="f-form"'):]
    assert form.index('class="f-alert"') < form.index("</form>")


def test_photo_from_analyse_is_kept_for_save(client):
    r = client.post("/analyse", data={"action": "analyse", "incident_id": "INC-070", "narrative": TEXT,
                                      "street": "Khiam", "photo_file": (io.BytesIO(JPEG), "p.jpg")},
                    content_type="multipart/form-data")
    name = re.search(r'<input type="hidden" name="photo" value="([^"]+)">', r.data.decode()).group(1)
    client.post("/analyse", data={"action": "save", "incident_id": "INC-070", "narrative": TEXT,
                                  "street": "Khiam", "photo": name})
    assert store.get_incident("INC-070").photo == name


def test_save_shows_confirmation_with_grid_and_next_steps(client):
    client.post("/seed")
    html = client.post("/analyse", data={
        "action": "save", "incident_id": "INC-042", "narrative": TEXT, "street": "Khiam",
        "mgrs": "36S YB 049 833", "item_color": "yellow", "item_color_other": "white stencil"}).data.decode()
    assert "INC-042 is on record" in html and "36S YB 049 833" in html
    assert 'href="/report">File another report' in html
    import app as sirens_app
    meta = json.loads(sirens_app.META_FILE.read_text())["INC-042"]
    assert meta["caza"] == "Sour" and abs(meta["lat"] - 33.2697) < 0.001
    assert meta["color"] == "yellow, white stencil"


def test_form_has_map_picker_type_tiles_and_drop_zone(client):
    html = client.get("/report").data.decode()
    assert 'id="pickmap"' in html and 'data-cazas="/map/cazas.geojson"' in html
    assert html.count('<label class="tile">') == 11                  # Not sure + 10 types
    assert html.count('<label class="sw">') == 11                    # Not stated + 10 colours
    assert 'class="drop"' in html and 'id="photo_file"' in html
    assert client.get("/map/cazas.geojson").json["features"]
