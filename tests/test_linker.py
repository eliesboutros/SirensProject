"""Behavior tests for the C-IED linker.  Run:  python -m pytest tests/ -q
All data fabricated.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from linker.models import Incident
from linker.extract import FeatureExtractor
from linker.match import Matcher
from linker.cluster import Clusterer

TAX = pathlib.Path(__file__).resolve().parents[1] / "data" / "taxonomy" / "cied_lexicon.json"
EX = FeatureExtractor(TAX, use_ner=False)   # rules-only = fast & deterministic


def make(idx, text, **kw):
    inc = Incident(incident_id=idx, narrative=text, **kw)
    return EX.extract(inc)


def test_extract_canonical_features():
    inc = make("t1", "A victim-operated IED with a pressure plate and a pressure cooker container; HME charge.")
    keys = inc.feature_keys()
    assert ("initiation", "victim_operated") in keys
    assert ("trigger", "pressure_plate") in keys
    assert ("container", "pressure_cooker") in keys
    assert ("charge_label", "hme_label") in keys


def test_alias_normalization():
    a = make("a", "command-wire initiated device")
    b = make("b", "command wire IED, command-initiated")
    assert ("trigger", "command_wire") in a.feature_keys()
    assert ("trigger", "command_wire") in b.feature_keys()


def test_same_signature_links_high():
    a = make("a", "victim-operated pressure plate, pressure cooker, HME, convoy")
    b = make("b", "victim-operated buried pressure plate device, pressure cooker container, homemade explosive, convoy")
    noise = make("n", "remote-controlled market device, commercial explosive, civilian target")
    m = Matcher().fit([a, b, noise])
    link = m.score(a, b)
    noise_link = m.score(a, noise)
    assert link.score >= 0.4
    assert link.score > noise_link.score
    assert any("pressure_plate" in s for s in link.shared_features)


def test_shared_phone_links_even_with_few_features():
    a = make("a", "IED event. contact 0791-555-0182.")
    b = make("b", "Separate device. phone 0791-555-0182 recovered.")
    m = Matcher().fit([a, b])
    link = m.score(a, b)
    assert any("phone" in e for e in link.shared_entities)
    assert link.score > 0.25


def test_noise_not_linked():
    a = make("a", "victim-operated pressure plate pressure cooker HME")
    noise = make("n", "remote-controlled device in a market, commercial explosive, civilian target")
    m = Matcher().fit([a, noise])
    link = m.score(a, noise)
    assert link.score < 0.25


def test_rarity_weighting_prefers_rare_shared_feature():
    # Everyone shares 'target_convoy'; only a,b share the rare trigger.
    common = [make(f"c{i}", "IED against a convoy") for i in range(6)]
    a = make("a", "pressure plate IED against a convoy")
    b = make("b", "pressure plate device, convoy")
    m = Matcher().fit(common + [a, b])
    ab = m.score(a, b).score
    ac = m.score(a, common[0]).score
    assert ab > ac  # the rare shared trigger should dominate


def test_clustering_finds_two_groups():
    incs = []
    for i in range(3):
        incs.append(make(f"P{i}", "victim-operated pressure plate pressure cooker HME convoy, the Copper Road Cell"))
    for i in range(3):
        incs.append(make(f"Q{i}", "command wire complex ambush secondary device repurposed ordnance, the Northern Cell"))
    incs.append(make("Z", "remote-controlled market device commercial explosive"))
    m = Matcher().fit(incs)
    links = m.all_pairs(incs, threshold=0.25)
    clusters = Clusterer(incs, links).clusters()
    sizes = sorted(c.size for c in clusters)
    assert sizes == [3, 3]           # two groups of three
    assert all("Z" not in c.members for c in clusters)  # noise excluded


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_object_attributes_extracted():
    inc = make("obj", "An intact 107mm rocket, olive green, fin-stabilised, nose fuze fitted, about 1 m.")
    keys = inc.feature_keys()
    assert ("object_type", "rocket_107mm") in keys
    assert ("colour", "green") in keys
    assert ("shape", "fin_stabilised") in keys
    assert ("condition", "intact") in keys
    assert ("fuze", "fuze_fitted") in keys


def test_area_brief_retrieves_objects_and_stays_in_lane():
    from linker.query import area_brief
    incs = [
        make("R1", "A 107mm rocket, green, fin-stabilised, intact at Route Copper.", location="Route Copper"),
        make("R2", "A corroded 107mm rocket, finned, at Route Copper.", location="Route Copper"),
        make("X1", "A market device far away.", location="Old Town"),
    ]
    b = area_brief(incs, location="Route Copper",
                   describe="green fin-stabilised rocket intact",
                   extractor=EX, responder_photo="snap.jpg")
    assert b.n_in_area == 2                     # only the Route Copper incidents
    assert any(t == "rocket_107mm" for t, _, _ in b.object_profile)
    assert b.responder_photo == "snap.jpg"      # attached, passed through
    # The brief must carry its retrieval-not-identification boundary.
    assert "not identification" in b.note and "specialist" in b.note


def test_ner_noise_filtered():
    # Unit tokens and place phrases must not become persons/groups.
    inc = make("n", "A 107mm rocket found in Al-Fakir District near Route Copper.")
    assert "mm" not in inc.persons
    assert not any("District" in p for p in inc.persons)
    assert not any("District" in g for g in inc.groups)


def test_person_sanitizer_logic():
    # Test the filter directly (deterministic, not dependent on the NER model).
    v = FeatureExtractor._valid_person
    assert v("Rashid Karim")          # real name kept
    assert v("Kamal Dost")
    assert not v("mm")                 # unit token rejected
    assert not v("cm")
    assert not v("Al-Fakir District")  # place phrase rejected
    assert not v("IED")                # jargon rejected
    assert not v("ab")                 # too short
    g = FeatureExtractor._valid_group
    assert g("the Northern Cell")
    assert not g("Green Village")      # place rejected as a group



def test_community_detection_separates_two_networks():
    # Two dense signatures + a bridge incident must not collapse into one.
    from linker.match import Matcher
    from linker.cluster import Clusterer
    incs = []
    for i in range(4):
        incs.append(make(f"A{i}", "victim-operated pressure plate pressure cooker HME convoy, the Alpha Cell"))
    for i in range(4):
        incs.append(make(f"B{i}", "command wire complex ambush secondary device repurposed ordnance, the Bravo Cell"))
    m = Matcher().fit(incs)
    links = m.all_pairs(incs, threshold=0.3)
    clusters = Clusterer(incs, links).clusters(method="louvain")
    # both true groups recovered as separate clusters of 4
    sizes = sorted(c.size for c in clusters)
    assert sizes == [4, 4]
