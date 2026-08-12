"""Persistent store for incidents (SQLite).

The command-line tool re-reads JSON/txt every run and forgets everything after.
For a product you want a *memory*: each report you analyse is saved, and every
new report is compared against the full accumulated history. That's what this
module gives you — a single local database file (no server, nothing to host)
that the web app reads from and writes to.

An Incident is stored with both its raw narrative *and* its already-extracted
features/entities, so loading the history back is instant (no re-extraction) and
still fully explainable — every stored value keeps the text it came from.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import datetime, timezone

from .models import Feature, Incident

DEFAULT_DB = pathlib.Path(__file__).resolve().parent.parent / "data" / "sirens.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    incident_id  TEXT PRIMARY KEY,
    date         TEXT,
    location     TEXT,
    grid         TEXT,
    narrative    TEXT NOT NULL,
    photo        TEXT,
    features     TEXT NOT NULL DEFAULT '[]',
    persons      TEXT NOT NULL DEFAULT '[]',
    groups_      TEXT NOT NULL DEFAULT '[]',
    phones       TEXT NOT NULL DEFAULT '[]',
    places       TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL
);
"""


def connect(db_path=None) -> sqlite3.Connection:
    """Open (and if needed create) the database, returning a live connection."""
    p = pathlib.Path(db_path or DEFAULT_DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


# -- (de)serialisation between Incident objects and DB rows -------------------
def _dump_features(inc: Incident) -> str:
    return json.dumps(
        [{"facet": f.facet, "value": f.value, "surface": f.surface} for f in inc.features]
    )


def _load_features(blob: str) -> list[Feature]:
    out = []
    for d in json.loads(blob or "[]"):
        out.append(Feature(d["facet"], d["value"], d.get("surface", "")))
    return out


def _row_to_incident(row: sqlite3.Row) -> Incident:
    return Incident(
        incident_id=row["incident_id"],
        date=row["date"],
        location=row["location"],
        grid=row["grid"],
        narrative=row["narrative"],
        photo=row["photo"],
        features=_load_features(row["features"]),
        persons=set(json.loads(row["persons"] or "[]")),
        groups=set(json.loads(row["groups_"] or "[]")),
        phones=set(json.loads(row["phones"] or "[]")),
        places=set(json.loads(row["places"] or "[]")),
    )


# -- write -------------------------------------------------------------------
def add_incident(inc: Incident, db_path=None, conn: sqlite3.Connection | None = None) -> None:
    """Insert or update a single incident (keyed on incident_id)."""
    own = conn is None
    conn = conn or connect(db_path)
    conn.execute(
        """INSERT INTO incidents
             (incident_id, date, location, grid, narrative, photo,
              features, persons, groups_, phones, places, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(incident_id) DO UPDATE SET
             date=excluded.date, location=excluded.location, grid=excluded.grid,
             narrative=excluded.narrative, photo=excluded.photo,
             features=excluded.features, persons=excluded.persons,
             groups_=excluded.groups_, phones=excluded.phones, places=excluded.places
        """,
        (
            inc.incident_id, inc.date, inc.location, inc.grid, inc.narrative, inc.photo,
            _dump_features(inc),
            json.dumps(sorted(inc.persons)), json.dumps(sorted(inc.groups)),
            json.dumps(sorted(inc.phones)), json.dumps(sorted(inc.places)),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    if own:
        conn.close()


def add_incidents(incidents: list[Incident], db_path=None) -> int:
    conn = connect(db_path)
    for inc in incidents:
        add_incident(inc, conn=conn)
    conn.close()
    return len(incidents)


# -- read --------------------------------------------------------------------
def all_incidents(db_path=None) -> list[Incident]:
    conn = connect(db_path)
    rows = conn.execute("SELECT * FROM incidents ORDER BY created_at").fetchall()
    conn.close()
    return [_row_to_incident(r) for r in rows]


def get_incident(incident_id: str, db_path=None) -> Incident | None:
    conn = connect(db_path)
    row = conn.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
    conn.close()
    return _row_to_incident(row) if row else None


def count(db_path=None) -> int:
    conn = connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    conn.close()
    return int(n)


def exists(incident_id: str, db_path=None) -> bool:
    conn = connect(db_path)
    row = conn.execute("SELECT 1 FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
    conn.close()
    return row is not None


def clear(db_path=None) -> None:
    conn = connect(db_path)
    conn.execute("DELETE FROM incidents")
    conn.commit()
    conn.close()


def next_incident_id(db_path=None, prefix: str = "INC") -> str:
    """Suggest the next free id like INC-014, based on what's already stored."""
    conn = connect(db_path)
    rows = conn.execute("SELECT incident_id FROM incidents").fetchall()
    conn.close()
    hi = 0
    for r in rows:
        tail = str(r["incident_id"]).rsplit("-", 1)[-1]
        if tail.isdigit():
            hi = max(hi, int(tail))
    return f"{prefix}-{hi + 1:03d}"
