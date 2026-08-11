"""Load incident reports into Incident objects.

Two input shapes are supported so the tool fits real workflows:
  * JSON — one object per incident with explicit fields (structured DBs/exports).
  * Free text — a .txt report; we take the filename as the id and the whole body
    as the narrative, then let extraction pull structure out of it.
"""
from __future__ import annotations

import json
import pathlib

from .models import Incident


def load_incidents(path: str | pathlib.Path) -> list[Incident]:
    p = pathlib.Path(path)
    incidents: list[Incident] = []
    if p.is_dir():
        for f in sorted(p.iterdir()):
            incidents.extend(_load_file(f))
    else:
        incidents.extend(_load_file(p))
    return incidents


def _load_file(f: pathlib.Path) -> list[Incident]:
    if f.suffix.lower() == ".json":
        data = json.loads(f.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else [data]
        out = []
        for i, rec in enumerate(records):
            out.append(
                Incident(
                    incident_id=str(rec.get("id") or rec.get("incident_id") or f"{f.stem}-{i}"),
                    date=rec.get("date"),
                    location=rec.get("location"),
                    grid=rec.get("grid"),
                    narrative=rec.get("narrative", "") or rec.get("text", ""),
                    photo=rec.get("photo"),
                )
            )
        return out
    if f.suffix.lower() in (".txt", ".md"):
        return [Incident(incident_id=f.stem, narrative=f.read_text(encoding="utf-8", errors="replace"))]
    return []
