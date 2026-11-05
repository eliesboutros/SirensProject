"""GPS point -> caza (linker/regions.py)."""
from linker import regions


def test_known_towns():
    assert regions.caza_at(33.8938, 35.5018) == "Beirut"
    assert regions.caza_at(34.4367, 35.8497) == "Tripoli"
    assert regions.caza_at(33.27, 35.20) == "Sour"
    assert regions.caza_at(34.0047, 36.2110) == "Baalbeck"


def test_outside_lebanon():
    assert regions.caza_at(33.9, 35.0) is None      # at sea
    assert regions.caza_at(48.85, 2.35) is None     # Paris


def test_names_are_unique():
    n = regions.names()
    assert len(n) == len(set(n)) and "BintJbayl" in n
