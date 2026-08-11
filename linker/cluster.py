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

    def clusters(self, singletons: bool = False, method: str = "louvain") -> list[Cluster]:
        """Group incidents into candidate networks.

        method='louvain'  : community detection (weight-aware). Resists merging
                            two real networks just because one bridge edge exists
                            — the right default at scale.
        method='components': connected components. Simple, but a single spurious
                            edge fuses whole networks; use only for tiny sets.
        """
        if method == "components":
            groups = [sorted(c) for c in nx.connected_components(self.graph)]
        else:
            groups = self._communities()

        out: list[Cluster] = []
        cid = 0
        for members in sorted(groups, key=len, reverse=True):
            members = sorted(members)
            if len(members) < 2 and not singletons:
                continue
            cid += 1
            mset = set(members)
            internal = [d["link"] for u, v, d in self.graph.edges(members, data=True)
                        if u in mset and v in mset]
            seen_pairs, uniq = set(), []
            for l in sorted(internal, key=lambda l: l.score, reverse=True):
                pair = frozenset((l.a, l.b))
                if pair not in seen_pairs:
                    seen_pairs.add(pair); uniq.append(l)
            out.append(Cluster(
                cluster_id=f"C{cid:02d}",
                members=members,
                signature=self._signature(members),
                internal_links=uniq,
            ))
        return out

    def _communities(self) -> list[list[str]]:
        """Weight-aware community detection over the link graph.

        Runs Louvain per connected component (isolated nodes stay singletons).
        Falls back to greedy modularity if Louvain is unavailable.
        """
        from networkx.algorithms import community as nx_comm
        groups: list[list[str]] = []
        for comp in nx.connected_components(self.graph):
            sub = self.graph.subgraph(comp)
            if sub.number_of_nodes() <= 2 or sub.number_of_edges() == 0:
                groups.append(list(comp))
                continue
            try:
                parts = nx_comm.louvain_communities(sub, weight="weight", seed=7)
            except Exception:
                parts = nx_comm.greedy_modularity_communities(sub, weight="weight")
            for p in parts:
                groups.append(list(p))
        return groups

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
