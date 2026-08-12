"""Tests for the added product layers: database, semantic matching, web app.

These don't require an API key or the vector model — the semantic layer falls
back to lexical similarity, and the AI panel is simply skipped when no key is set.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from linker import store, semantic
from linker.models import Feature, Incident


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr(store, "DEFAULT_DB", db)
    return db


def _mk(id_, narrative, feats=()):
    inc = Incident(incident_id=id_, narrative=narrative)
    inc.features = [Feature(f, v, s) for (f, v, s) in feats]
    return inc


def test_store_roundtrip(tmp_db):
    inc = _mk("INC-001", "A buried device on Route Copper.",
              feats=[("trigger", "pressure_plate", "pressure plate")])
    inc.phones.add("0791-555-0182")
    store.add_incident(inc)
    assert store.count() == 1
    back = store.all_incidents()[0]
    assert back.incident_id == "INC-001"
    assert back.narrative == inc.narrative
    assert ("trigger", "pressure_plate") in back.feature_keys()
    assert "0791-555-0182" in back.phones


def test_store_upsert_and_next_id(tmp_db):
    store.add_incident(_mk("INC-001", "one"))
    store.add_incident(_mk("INC-001", "one edited"))  # same id -> update, not dup
    assert store.count() == 1
    store.add_incident(_mk("INC-004", "four"))
    assert store.next_incident_id() == "INC-005"


def test_store_clear(tmp_db):
    store.add_incident(_mk("INC-001", "x"))
    store.clear()
    assert store.count() == 0


def test_semantic_similarity_bounds():
    s = semantic.similarity("a buried IED on the road", "a device concealed in the road")
    assert 0.0 <= s <= 1.0
    # identical text is maximally similar
    assert semantic.similarity("same text here", "same text here") >= 0.9


def test_semantic_ranks_related_above_unrelated():
    a = "a buried victim operated IED struck a convoy on the road"
    related = "a concealed device detonated under a vehicle on the route"
    unrelated = "a green finned rocket was recovered intact by the market"
    assert semantic.similarity(a, related) > semantic.similarity(a, unrelated)


def test_web_app_analyse_returns_results(tmp_db):
    import app as web
    store.add_incident(_mk("INC-001",
        "buried pressure plate IED with pressure cooker on Route Copper"))
    client = web.app.test_client()
    r = client.post("/analyse", data={
        "incident_id": "INC-900",
        "narrative": "a concealed pressure plate device on the Copper route",
        "action": "analyse"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Signature extracted" in body
    assert "INC-900" in body


def test_cli_import_and_db_share_one_store(tmp_db, capsys):
    """A report imported via the CLI and one saved elsewhere both land in the
    same database, and `cli db` analyses all of them — the single source of truth."""
    import types
    import cli
    samples = str(cli.pathlib.Path(cli.__file__).parent / "data" / "sample_incidents")

    rc = cli.cmd_import(types.SimpleNamespace(
        target=samples, taxonomy=str(cli.TAXONOMY), no_ner=False))
    assert rc == 0
    n = store.count()
    assert n >= 10

    rc = cli.cmd_db(types.SimpleNamespace(threshold=0.25, html=None, json=None))
    assert rc == 0
    assert "LINK ANALYSIS" in capsys.readouterr().out

    # simulate the web console saving a new report into the same store
    store.add_incident(_mk("INC-777",
        "command wire complex ambush secondary device, the Northern Cell"))
    assert store.count() == n + 1

    cli.cmd_db(types.SimpleNamespace(threshold=0.25, html=None, json=None))
    assert f"analysing {n + 1}" in capsys.readouterr().out


def test_cli_db_empty_is_graceful(tmp_db, capsys):
    import types
    import cli
    rc = cli.cmd_db(types.SimpleNamespace(threshold=0.25, html=None, json=None))
    assert rc == 2
    assert "empty" in capsys.readouterr().out.lower()
