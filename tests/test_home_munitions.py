"""Home page, munitions reference page, and the guarded "delete every report"."""
import re
from datetime import date

from linker import decisions, store


def test_empty_home_invites_first_steps(client):
    html = client.get("/").data.decode()
    assert "No reports on record yet." in html
    assert 'href="/report"' in html and 'href="/demo"' in html
    assert "Reports you file appear here" in html


def test_home_states_the_record(client):
    client.post("/seed")
    html = client.get("/").data.decode()
    m = re.search(r'<h1 id="state">40 reports on record\. <span class="quiet">(\d+) links are waiting', html)
    assert m, "headline should count reports and open links"
    n_open = int(m.group(1))
    assert f'<b class="count num">{n_open}</b>' in html          # badge on Review links
    assert html.count('<span class="band ') == 5                   # top five waiting links
    assert html.count('<span class="id">INC-') >= 6 + 10           # recent + link pairs
    # Deciding a link removes it from the waiting count.
    a, b = re.search(r'<span class="id">(INC-\d+)</span> and <span class="id">(INC-\d+)</span>', html).groups()
    decisions.set_decision(a, b, "confirm")
    assert f"{n_open - 1} links are waiting" in client.get("/").data.decode()


def test_activity_strip_counts_months():
    import home_bp

    class I:
        def __init__(self, d): self.date = d
    s = home_bp.activity([I("2026-11-02"), I("2026-11-20"), I("2026-01-05"), I("2025-10-01"), I(None)],
                         today=date(2026, 11, 5))
    assert [b["n"] for b in s["bars"]][-1] == 2
    assert s["bars"][0]["label"] == "Dec 2025" and s["last"] == "Nov 2026"
    assert s["total"] == 3                                        # Oct 2025 is outside the window


def test_headline_wording():
    import home_bp
    assert home_bp.headline(1, 0, 0) == ("1 report on record.", "No links between them yet.")
    assert home_bp.headline(5, 1, 3)[1] == "1 link is waiting for an analyst."
    assert home_bp.headline(5, 0, 3)[1] == "All 3 links have been reviewed."


def test_report_form_moved_to_its_own_page(client):
    html = client.get("/report").data.decode()
    assert 'action="/analyse"' in html and "File a new report" in html
    assert "Munitions reference</h2>" not in html                # the old block is gone
    assert 'action="/clear"' not in html                         # no wipe button next to the form


def test_munitions_page_groups_every_entry(client):
    client.post("/seed")
    html = client.get("/munitions").data.decode()
    cards = re.findall(r'<details class="mcard" id="ref-([a-z0-9_]+)" data-fam="([a-z]+)"', html)
    assert len(cards) == 42
    assert {f for _, f in cards} >= {"mortar", "rocket", "artillery", "mine", "ied", "drone"}
    mortars = [k for k, f in cards if f == "mortar"]
    assert mortars[:4] == ["mortar_60mm", "mortar_81mm", "mortar_82mm", "mortar_120mm"]
    assert "not device-handling or render-safe guidance" in html
    assert html.count('class="note" role="note"') >= 40           # per-entry responder notes
    assert re.search(r"Mentioned in \d+ reports? on record", html)
    assert "<svg" in html and "http" not in re.sub(r'https?://(www\.)?w3\.org[^"]*', "", html.split("<body>")[1])


def test_clear_needs_typed_confirmation(client):
    client.post("/seed")
    r = client.post("/clear", data={"confirm": "clear"})
    assert r.status_code == 302 and "clear=refused" in r.headers["Location"]
    assert store.count() == 40
    assert "Nothing was deleted" in client.get("/demo?clear=refused").data.decode()
    client.post("/clear", data={"confirm": "CLEAR"})
    assert store.count() == 0
    assert "Type CLEAR to confirm" in client.get("/demo").data.decode()
