"""Saving a report shows its likely network with band + reasons (temporary database)."""
import re

from linker.cluster import Clusterer
from linker.match import Matcher
from linker import store

# Fabricated, descriptive wording only (analyst-level vocabulary).
REPORT = ("Fabricated test report. A remote-controlled IED was found concealed in a culvert "
          "near Srifa, targeting a patrol.")


def _save(client, incident_id, narrative, street="Srifa"):
    return client.post("/analyse", data={"incident_id": incident_id, "street": street,
                                         "narrative": narrative, "action": "save"})


def test_saved_report_page_loads_the_network_panel(client):
    client.post("/seed")
    html = _save(client, "INC-041", REPORT).data.decode()
    assert 'hx-get="/network/INC-041/panel"' in html
    assert "/static/vendor/htmx.min.js" in html


def test_analyse_without_saving_shows_no_panel(client):
    client.post("/seed")
    r = client.post("/analyse", data={"incident_id": "INC-041", "narrative": REPORT, "action": "analyse"})
    assert "/network/INC-041/panel" not in r.data.decode()


def test_panel_matches_the_link_tree_clustering(client):
    client.post("/seed")
    _save(client, "INC-041", REPORT)
    incs = store.all_incidents()
    links = Matcher().fit(incs).all_pairs(incs, threshold=0.25)
    cluster = next(c for c in Clusterer(incs, links).clusters() if "INC-041" in c.members)

    r = client.get("/network/INC-041/panel")
    assert r.status_code == 200
    html = r.data.decode()
    assert f"candidate network <strong class=\"mono\">{cluster.cluster_id}</strong>" in html
    assert f"({cluster.size} incidents)" in html
    best = max((l for l in links if "INC-041" in (l.a, l.b)
                and ({l.a, l.b} - {"INC-041"}) <= set(cluster.members)), key=lambda l: l.score)
    band = "strong" if best.score >= 0.66 else "medium" if best.score >= 0.40 else "weak"
    assert f"({band})" in re.sub(r"</?strong>", "", html)
    from report_view import reason_label
    assert reason_label(best.reasons[0]) in html                  # the reasons are shown, in words
    assert "not a conclusion" in html


def test_report_with_no_links_says_so(client):
    client.post("/seed")
    _save(client, "INC-050", "Fabricated. Nothing descriptive in this text.", street="")
    r = client.get("/network/INC-050/panel")
    assert r.status_code == 200 and b"No likely network yet" in r.data


def test_unknown_incident_is_404(client):
    assert client.get("/network/NOPE/panel").status_code == 404
