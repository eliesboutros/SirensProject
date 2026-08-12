#!/usr/bin/env python3
"""C-IED Incident Link Analysis — command line.

Two modes:

  analyze : link incidents into candidate networks/signatures
    python cli.py analyze data/sample_incidents/ --html link_chart.html

  brief   : record-based pre-arrival brief for an area (+ optional description)
    python cli.py brief data/sample_incidents/ --location "Route Copper" \
        --describe "small green fin-stabilised rocket, intact, nose fuze" \
        --photo responder_snap.jpg
"""
from __future__ import annotations

import argparse
import json
import pathlib

from linker.ingest import load_incidents
from linker.extract import FeatureExtractor
from linker.match import Matcher
from linker.cluster import Clusterer
from linker.report import console_report, html_report, static_graph_png, console_brief
from linker.query import area_brief
from linker import store

TAXONOMY = pathlib.Path(__file__).parent / "data" / "taxonomy" / "cied_lexicon.json"


def _load(target, taxonomy, use_ner):
    incidents = load_incidents(target)
    if not incidents:
        return None, None
    extractor = FeatureExtractor(taxonomy, use_ner=use_ner)
    extractor.extract_all(incidents)
    return incidents, extractor


def cmd_analyze(args) -> int:
    incidents, _ = _load(args.target, args.taxonomy, not args.no_ner)
    if not incidents:
        print("no incidents found"); return 2
    if getattr(args, "persist", False):
        store.add_incidents(incidents)
        print(f"[+] saved {len(incidents)} report(s) to the database "
              f"({store.count()} total)\n")
    matcher = Matcher().fit(incidents)
    links = matcher.all_pairs(incidents, threshold=args.threshold)
    clusterer = Clusterer(incidents, links)
    clusters = clusterer.clusters()
    print(console_report(incidents, links, clusters))
    if args.html:
        payload = clusterer.graph_payload()
        pathlib.Path(args.html).write_text(
            html_report(incidents, links, clusters, payload), encoding="utf-8")
        print(f"\n[+] interactive link chart -> {args.html}")
    if args.png:
        static_graph_png(clusterer, args.png)
        print(f"[+] static link chart -> {args.png}")
    if args.json:
        out = {"incidents": [i.to_dict() for i in incidents],
               "links": [l.to_dict() for l in links],
               "clusters": [c.to_dict() for c in clusters]}
        pathlib.Path(args.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"[+] json -> {args.json}")
    return 0


def cmd_brief(args) -> int:
    incidents, extractor = _load(args.target, args.taxonomy, not args.no_ner)
    if not incidents:
        print("no incidents found"); return 2
    brief = area_brief(incidents, location=args.location, describe=args.describe,
                       extractor=extractor, responder_photo=args.photo, top=args.top)
    print(console_brief(brief))
    if args.json:
        from dataclasses import asdict
        pathlib.Path(args.json).write_text(json.dumps(asdict(brief), indent=2),
                                           encoding="utf-8")
        print(f"\n[+] json -> {args.json}")
    return 0


def cmd_import(args) -> int:
    """Load a folder of reports into the database (the shared source of truth)."""
    incidents, _ = _load(args.target, args.taxonomy, not args.no_ner)
    if not incidents:
        print("no incidents found"); return 2
    store.add_incidents(incidents)
    print(f"[+] imported {len(incidents)} report(s) into the database")
    print(f"[=] the database now holds {store.count()} incident(s)")
    return 0


def cmd_db(args) -> int:
    """Analyse everything currently saved in the database."""
    incidents = store.all_incidents()
    if not incidents:
        print("the database is empty.")
        print("add reports in the web console (python app.py), or import a folder:")
        print("    python cli.py import data/sample_incidents")
        return 2
    matcher = Matcher().fit(incidents)
    links = matcher.all_pairs(incidents, threshold=args.threshold)
    clusterer = Clusterer(incidents, links)
    clusters = clusterer.clusters()
    print(f"[db] analysing {store.count()} saved incident(s)\n")
    print(console_report(incidents, links, clusters))
    if args.html:
        payload = clusterer.graph_payload()
        pathlib.Path(args.html).write_text(
            html_report(incidents, links, clusters, payload), encoding="utf-8")
        print(f"\n[+] interactive link chart -> {args.html}")
    if args.json:
        out = {"incidents": [i.to_dict() for i in incidents],
               "links": [l.to_dict() for l in links],
               "clusters": [c.to_dict() for c in clusters]}
        pathlib.Path(args.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"[+] json -> {args.json}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="C-IED incident link analysis")
    ap.add_argument("--taxonomy", default=str(TAXONOMY))
    ap.add_argument("--no-ner", action="store_true", help="disable spaCy NER layer")
    sub = ap.add_subparsers(dest="mode", required=True)

    a = sub.add_parser("analyze", help="link incidents into networks/signatures")
    a.add_argument("target")
    a.add_argument("--threshold", type=float, default=0.25)
    a.add_argument("--persist", action="store_true",
                   help="also save these reports into the shared database")
    a.add_argument("--html"); a.add_argument("--png"); a.add_argument("--json")
    a.set_defaults(func=cmd_analyze)

    imp = sub.add_parser("import", help="load a folder of reports into the database")
    imp.add_argument("target")
    imp.set_defaults(func=cmd_import)

    d = sub.add_parser("db", help="analyse everything saved in the database")
    d.add_argument("--threshold", type=float, default=0.25)
    d.add_argument("--html"); d.add_argument("--json")
    d.set_defaults(func=cmd_db)

    b = sub.add_parser("brief", help="record-based pre-arrival brief for an area")
    b.add_argument("target")
    b.add_argument("--location", required=True, help="area / place to query")
    b.add_argument("--describe", default=None, help="free-text description of the object")
    b.add_argument("--photo", default=None, help="responder photo (attached, NOT analysed)")
    b.add_argument("--top", type=int, default=5)
    b.add_argument("--json")
    b.set_defaults(func=cmd_brief)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
