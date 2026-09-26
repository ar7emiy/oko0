"""Read-time identity projection: links underneath, a merged view on top.

Nothing is ever physically merged. The linker writes scored links between
mentions; this module groups mentions into entities when something reads
them, at a lens the reader picks. The notebook's dossiers and the search app
both call `project`, so the two can never disagree about what "merged" means.

A link is a dict with at least:
    a, b         mention keys
    p            posterior probability the two are the same party (0..1)
    basis_class  "identifier" | "address" | "dob" | "co_party" | "name_only" | "none"
    veto         None, or the reason the pair can never be one party

Lenses:
    strict   only identifier-backed links
    default  any basis, high probability
    broad    any basis, including partial name matches

Clusters are built greedily from the strongest link down (Kruskal), so the
links a cluster uses form its maximum spanning tree, and the weakest link on
that tree is the cluster's confidence: a chain is only as strong as its
weakest edge. A union that would put a vetoed pair into one cluster is
refused, and so is one that would grow a cluster past `max_size`: a shared
clinic phone line must not chain dozens of unrelated people together.
"""
from collections import defaultdict

LENSES = {
    "strict":  {"min_p": 0.90, "basis": {"identifier"},
                "label": "Identifier-backed links only"},
    "default": {"min_p": 0.80, "basis": None,
                "label": "Any basis, high confidence"},
    "broad":   {"min_p": 0.10, "basis": None,
                "label": "Adds partial and weak name matches"},
}
MAX_CLUSTER = 40


def admits(link, lens):
    spec = LENSES[lens]
    if link.get("veto"):
        return False
    if link.get("basis_class") == "none":
        return False        # no field agreed: a prior alone never merges anything
    if link["p"] < spec["min_p"]:
        return False
    return spec["basis"] is None or link["basis_class"] in spec["basis"]


def project(mention_keys, links, lens="default", max_size=MAX_CLUSTER):
    """Group mentions into clusters under a lens.

    Returns {"clusters": [...], "refused": [...], "lens": lens}. Each cluster:
        id          its lowest member key (stable while that mention exists)
        members     sorted mention keys
        edges       the links that built it (its spanning tree)
        joined_by   {member: the link that pulled it in, or None for the first}
        weakest     the lowest-probability link on the tree, or None if singleton
    """
    keys = sorted(set(mention_keys))
    parent = {k: k for k in keys}
    size = {k: 1 for k in keys}
    comp_members = {k: {k} for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    vetoed = defaultdict(set)
    for l in links:
        if l.get("veto") and l["a"] in parent and l["b"] in parent:
            vetoed[l["a"]].add(l["b"]); vetoed[l["b"]].add(l["a"])

    used, refused = [], []
    ordered = sorted((l for l in links if l["a"] in parent and l["b"] in parent and admits(l, lens)),
                     key=lambda l: (-l["p"], l["a"], l["b"]))
    for l in ordered:
        ra, rb = find(l["a"]), find(l["b"])
        if ra == rb:
            continue
        ma, mb = comp_members[ra], comp_members[rb]
        clash = next(((x, y) for x in ma for y in vetoed[x] if y in mb), None)
        if clash:
            refused.append({"link": l, "reason": "veto", "would_merge": sorted(clash)})
            continue
        if size[ra] + size[rb] > max_size:
            refused.append({"link": l, "reason": "cluster_size",
                            "would_reach": size[ra] + size[rb]})
            continue
        if size[ra] < size[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        size[ra] += size[rb]
        comp_members[ra] |= comp_members.pop(rb)
        used.append(l)

    tree_edges = defaultdict(list)
    for l in used:
        tree_edges[find(l["a"])].append(l)

    clusters = []
    for root, members in comp_members.items():
        if find(root) != root:
            continue
        ms = sorted(members)
        edges = sorted(tree_edges.get(root, []), key=lambda l: -l["p"])
        joined = {ms[0]: None}
        # walk the tree from the lowest key so every member names the link that reached it
        adj = defaultdict(list)
        for l in edges:
            adj[l["a"]].append((l["b"], l)); adj[l["b"]].append((l["a"], l))
        stack = [ms[0]]
        while stack:
            x = stack.pop()
            for y, l in adj[x]:
                if y not in joined:
                    joined[y] = l; stack.append(y)
        clusters.append({"id": ms[0], "members": ms, "edges": edges, "joined_by": joined,
                         "weakest": min(edges, key=lambda l: l["p"]) if edges else None})
    clusters.sort(key=lambda c: c["id"])
    return {"lens": lens, "clusters": clusters, "refused": refused}


def subtree_weakest(cluster, subset):
    """Weakest link on the part of a cluster's tree that connects `subset`.

    A claim's view of a cross-claim cluster keeps only that claim's members,
    but the path joining them may run through other claims. The confidence of
    the claim-level entity is the weakest link on that connecting path, not
    on the whole cluster."""
    subset = set(subset) & set(cluster["members"])
    if len(subset) < 2:
        return None
    adj = defaultdict(dict)
    for l in cluster["edges"]:
        adj[l["a"]][l["b"]] = l; adj[l["b"]][l["a"]] = l
    live = set(cluster["members"])
    changed = True
    while changed:                      # prune leaves that are not in the subset
        changed = False
        for x in list(live):
            if x not in subset and len([y for y in adj[x] if y in live]) <= 1:
                live.discard(x); changed = True
    edges = {id(l): l for x in live for y, l in adj[x].items() if y in live}
    return min(edges.values(), key=lambda l: l["p"]) if edges else None
