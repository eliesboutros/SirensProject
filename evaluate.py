#!/usr/bin/env python3
"""Evaluate the linker against a ground-truth key.

Metric: pairwise linkage precision / recall / F1. For every pair of incidents we
compare truth ("same network?") against the tool's prediction ("same cluster?").
This is the standard, honest way to score record linkage and is the metric named
in the proposal.

    python evaluate.py --data data/generated --threshold 0.30
    python evaluate.py --data data/generated --sweep
"""
from __future__ import annotations

import argparse
import json
import pathlib
from itertools import combinations

from linker.ingest import load_incidents
from linker.extract import FeatureExtractor
from linker.match import Matcher
from linker.cluster import Clusterer

TAX = pathlib.Path(__file__).parent / "data" / "taxonomy" / "cied_lexicon.json"


def _load_truth(path):
    """Accept either {id: label} or [{'id':..,'cluster':..}, ...]."""
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw
    return {r["id"]: r.get("cluster", r.get("network")) for r in raw}


def evaluate(data_dir, threshold, taxonomy, use_ner=True):
    data = pathlib.Path(data_dir)
    incidents = load_incidents(str(data / "incidents.json"))
    truth = _load_truth(data / "ground_truth.json")

    FeatureExtractor(taxonomy, use_ner=use_ner).extract_all(incidents)
    links = Matcher().fit(incidents).all_pairs(incidents, threshold=threshold)
    clusters = Clusterer(incidents, links).clusters()

    pred = {}
    for c in clusters:
        for m in c.members:
            pred[m] = c.cluster_id
    for i in incidents:
        pred.setdefault(i.incident_id, f"SINGLETON:{i.incident_id}")

    def same_truth(a, b):
        ta, tb = truth.get(a), truth.get(b)
        return ta == tb and ta not in (None, "NOISE")

    def same_pred(a, b):
        return pred[a] == pred[b] and not pred[a].startswith("SINGLETON")

    tp = fp = fn = 0
    ids = [i.incident_id for i in incidents]
    for a, b in combinations(ids, 2):
        t, p = same_truth(a, b), same_pred(a, b)
        if t and p: tp += 1
        elif p and not t: fp += 1
        elif t and not p: fn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    true_nets = len({v for v in truth.values() if v != "NOISE"})
    return {"incidents": len(incidents), "threshold": threshold,
            "true_networks": true_nets, "clusters_found": len(clusters),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/generated")
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--no-ner", action="store_true")
    ap.add_argument("--taxonomy", default=str(TAX))
    args = ap.parse_args()

    if args.sweep:
        print(f"{'thresh':>7} {'prec':>6} {'recall':>7} {'f1':>6} {'clusters':>9}")
        print("-" * 40)
        best = None
        for t in [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
            r = evaluate(args.data, t, args.taxonomy, not args.no_ner)
            print(f"{t:>7.2f} {r['precision']:>6} {r['recall']:>7} {r['f1']:>6} {r['clusters_found']:>9}")
            best = r if best is None or r["f1"] > best["f1"] else best
        print("-" * 40)
        print(f"best F1={best['f1']} at threshold {best['threshold']} "
              f"(precision {best['precision']}, recall {best['recall']})")
    else:
        print(json.dumps(evaluate(args.data, args.threshold, args.taxonomy, not args.no_ner), indent=2))


if __name__ == "__main__":
    main()
