"""Turn pairwise links into clusters ('candidate networks / signatures').

We build a graph (nodes = incidents, edges = links above threshold) and take
connected components as clusters. For each cluster we compute the descriptive
features common to a majority of its members — that's the group's signature, and
the first thing an analyst wants to see.

networkx also gives us optional community detection for splitting large, loosely
connected components into tighter sub-groups.
"""
from __future__ import annotations

from collections import Counter

import networkx as nx

from .models import Cluster, Incident, Link


class Clusterer:
    def __init__(self, incidents: list[Incident], links: list[Link]):
        self.by_id = {i.incident_id: i for i in incidents}
        self.incidents = incidents
        self.links = links
        self.graph = self._build_graph()

    def _build_graph(self) -> nx.Graph:
        g = nx.Graph()
        for inc in self.incidents:
            g.add_node(inc.incident_id)
        for l in self.links:
            g.add_edge(l.a, l.b, weight=l.score, link=l)
        return g

    def _signature(self, members: list[str], min_fraction: float = 0.6) -> list[str]:
        counts: Counter = Counter()
        for mid in members:
            for f in self.by_id[mid].features:
                counts[f.key()] += 1
        need = max(2, int(len(members) * min_fraction)) if len(members) > 1 else 1
        sig = [f"{f}={v}" for (f, v), c in counts.most_common() if c >= need]
        return sig

    def clusters(self, singletons: bool = False) -> list[Cluster]:
        out: list[Cluster] = []
        cid = 0
        for comp in sorted(nx.connected_components(self.graph), key=len, reverse=True):
            members = sorted(comp)
            if len(members) < 2 and not singletons:
                continue
            cid += 1
            internal = [
                d["link"]
                for u, v, d in self.graph.edges(members, data=True)
                if u in comp and v in comp
            ]
            seen_pairs = set()
            uniq = []
            for l in sorted(internal, key=lambda l: l.score, reverse=True):
                pair = frozenset((l.a, l.b))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    uniq.append(l)
            internal = uniq
            out.append(
                Cluster(
                    cluster_id=f"C{cid:02d}",
                    members=members,
                    signature=self._signature(members),
                    internal_links=internal,
                )
            )
        return out

    def graph_payload(self) -> dict:
        """Node/edge lists for the HTML force-directed visualization."""
        # Assign each node its cluster id for coloring.
        node_cluster = {}
        for c in self.clusters(singletons=False):
            for m in c.members:
                node_cluster[m] = c.cluster_id
        nodes = []
        for inc in self.incidents:
            top_feats = [f"{f.facet}={f.value}" for f in inc.features[:4]]
            nodes.append({
                "id": inc.incident_id,
                "cluster": node_cluster.get(inc.incident_id, ""),
                "location": inc.location or "",
                "date": inc.date or "",
                "features": top_feats,
            })
        edges = [
            {"source": l.a, "target": l.b, "score": l.score,
             "reasons": l.reasons}
            for l in self.links
        ]
        return {"nodes": nodes, "edges": edges}
