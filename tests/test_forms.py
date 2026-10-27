"""Shared form design: help on every field, Arabic input, chips, notes, saving."""
import re
from html.parser import HTMLParser

import pytest

from linker import decisions, store

ARABIC_NARRATIVE = "تقرير مختلق للاختبار. عبوة على جانب الطريق قرب يارون، سلك تحكم."
ARABIC_PLACE = "يارون"


class _Controls(HTMLParser):
    """Collect every user-facing control inside an .f-form, and every (i) help target."""
    def __init__(self):
        super().__init__()
        self.depth, self.form_depth, self.controls, self.helps = 0, [], [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag not in ("input", "br", "img", "meta", "link", "option"):
            self.depth += 1
        classes = (a.get("class") or "").split()
        if "f-form" in classes:
            self.form_depth.append(self.depth)
        if tag == "button" and "f-help" in classes:
            self.helps.add(a.get("data-for"))
        if self.form_depth and tag in ("input", "select", "textarea"):
            if tag == "input" and a.get("type") in ("hidden", "submit", "button"):
                return
            self.controls.append((tag, a))

    def handle_endtag(self, tag):
        if tag not in ("input", "br", "img", "meta", "link", "option"):
            if self.form_depth and self.form_depth[-1] == self.depth:
                self.form_depth.pop()
            self.depth -= 1


def _parse(html):
    p = _Controls()
    p.feed(html)
    return p


PAGES = ["/", "/brief", "/review", "/dashboard"]


@pytest.mark.parametrize("path", PAGES)
def test_every_form_field_has_help(client, path):
    client.post("/seed")
    p = _parse(client.get(path).data.decode())
    assert p.controls, path
    missing = []
    for tag, a in p.controls:
        key = a.get("id") if a.get("type") not in ("radio", "checkbox") or a.get("id") else a.get("name")
        if key not in p.helps:
            missing.append(a.get("name"))
    assert not missing, f"{path}: fields without (i) help: {missing}"
    for target in p.helps:                       # every help has its text
        assert f'id="h-{target}"' in client.get(path).data.decode()


@pytest.mark.parametrize("path", ["/", "/brief", "/review"])       # the dashboard has no free-text boxes
def test_text_inputs_have_dir_auto(client, path):
    client.post("/seed")
    p = _parse(client.get(path).data.decode())
    texts = [a for tag, a in p.controls if tag == "textarea" or (tag == "input" and a.get("type", "text") == "text")]
    assert texts
    assert all(a.get("dir") == "auto" for a in texts), [a.get("name") for a in texts if a.get("dir") != "auto"]


def test_help_texts_stay_in_the_descriptive_lane():
    from forms_ui import HELP
    banned = ("render safe", "render-safe", "defuse", "disarm", "safe route", "approach the", "how to move")
    for key, text in HELP.items():
        assert text and not any(b in text.lower() for b in banned), key
    assert "does not identify" in HELP["brief_describe"]


def test_arabic_report_round_trip(client):
    r = client.post("/analyse", data={"incident_id": "INC-090", "narrative": ARABIC_NARRATIVE,
                                      "street": ARABIC_PLACE, "action": "save"})
    assert r.status_code == 200
    inc = store.get_incident("INC-090")
    assert inc.narrative == ARABIC_NARRATIVE
    assert ARABIC_PLACE in inc.location
    # The brief lists the stored report under "Incidents on record here", text unchanged.
    brief = client.post("/brief", data={"location": ARABIC_PLACE}).data.decode()
    assert "Incidents on record here" in brief and ARABIC_NARRATIVE in brief
    # A form sent back after an error keeps what was typed, unchanged.
    again = client.post("/analyse", data={"narrative": "", "street": ARABIC_PLACE, "action": "save"}).data.decode()
    assert re.search(r'id="street"[^>]*value="' + ARABIC_PLACE + '"', again)
    redo = client.post("/brief", data={"location": ARABIC_PLACE, "describe": "وصف للمقارنة"}).data.decode()
    assert "وصف للمقارنة</textarea>" in redo


def test_arabic_note_round_trip(client):
    client.post("/seed")
    html = client.get("/review").data.decode()
    a, b = re.search(r'name="a" value="([^"]+)"><input type="hidden" name="b" value="([^"]+)"', html).groups()
    note = "ملاحظة: التواريخ متباعدة."
    r = client.post("/review/note", data={"a": a, "b": b, "note": note, "analyst": "ب.ع"})
    assert r.status_code == 200 and note in r.data.decode()
    assert decisions.notes_for(a, b)[0]["note"] == note


def test_dashboard_filter_chips_add_and_remove(client):
    client.post("/seed")
    assert 'class="f-chip"' not in client.get("/dashboard").data.decode()
    html = client.get("/dashboard?area=Yaroun&initiation=victim_operated").data.decode()
    chips = re.findall(r'<a class="f-chip" href="([^"]+)"[^>]*>([^<]+)<', html)
    labels = [t.strip() for _, t in chips]
    assert labels == ["Area: Yaroun", "Method: victim operated"]
    remove_area = dict((t.strip(), u) for u, t in chips)["Area: Yaroun"].replace("&amp;", "&")
    assert "area=" not in remove_area and "initiation=victim_operated" in remove_area
    after = client.get(remove_area).data.decode()
    assert re.findall(r'<a class="f-chip"[^>]*>([^<]+)<', after)[0].strip() == "Method: victim operated"
    assert 'class="f-clear" href="/dashboard"' in html


def test_review_filter_chip(client):
    client.post("/seed")
    html = client.get("/review?show=reject").data.decode()
    assert re.search(r'<a class="f-chip" href="/review"[^>]*>Decision: rejected', html)
    assert 'class="f-chip"' not in client.get("/review").data.decode()


def test_location_suggestions_and_unknown_place_note(client):
    html = client.get("/").data.decode()
    street = re.search(r'<input[^>]*id="street"[^>]*>', html, re.S).group(0)
    assert 'list="placelist"' in street and 'data-rules="place:placelist:caza"' in street
    places = re.search(r'<datalist id="placelist">(.*?)</datalist>', html, re.S).group(1)
    assert 'value="Yaroun"' in places and 'value="Marjaayoun"' in places
    js = client.get("/static/forms.js").data.decode()
    assert "Not a known place; it may not appear on the map." in js


def test_saved_confirmation_and_likely_network(client):
    client.post("/seed")
    html = client.post("/analyse", data={"incident_id": "INC-041", "action": "save",
                                         "narrative": "Fabricated test. Command wire near Yaroun."}).data.decode()
    assert re.search(r'class="f-saved" role="status">Saved <strong class="mono">INC-041</strong>', html)
    assert 'hx-get="/network/INC-041/panel"' in html
    assert 'data-busy-text="Saving…"' in html


def test_server_error_is_shown_next_to_the_form(client):
    html = client.post("/analyse", data={"narrative": "", "action": "save"}).data.decode()
    form = html[html.index('<form class="f-form"'):]
    assert form.index('class="f-alert"') < form.index("</form>")


def test_oversized_upload_gets_a_calm_page(client):
    import io
    big = io.BytesIO(b"0" * (9 * 1024 * 1024))
    r = client.post("/analyse", data={"narrative": "x", "action": "save", "photo_file": (big, "big.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 413
    assert b"larger than 8 MB" in r.data and b"Traceback" not in r.data
    assert b'<nav class="sm"' in r.data
