# ---- Matching core v1.1: pooled entities and consistent clusters -----------------------------
# A pooled entity (several records about one party) is compared through its members: every
# member against the other record, then per field the best level any member reached. Clusters
# are built by greedy union-find with cannot-link constraints, so they are transitive and never
# hold two different values of a one-per-party identifier.


def aggregate_member_levels(lv, group, fields, k=None):
    """Member-level comparisons -> one row per group (an entity x a record): per field the best
    level any member reached (the null level only when no member had a value), the u factor of
    the member that reached it (the smallest on ties), the row of `lv` that supplied it
    (src_<field>), and a veto only when some member vetoes and none agrees exactly. `group`:
    dense group index 0..G-1 per row of lv. `k`: optional {field: array per group} of the
    distinct values the entity offered, written as k_<field> for the scorer."""
    group = np.asarray(group, dtype=np.int64)
    G = int(group.max()) + 1 if len(group) else 0
    rows = np.arange(len(lv))
    out = {}
    for f in fields:
        if f not in lv:
            continue
        code = lv[f].to_numpy().astype(np.int64)
        key = np.where(code >= 0, code, 1000)
        uv = lv[f"uv_{f}"].to_numpy(dtype=float) if f"uv_{f}" in lv else np.full(len(lv), np.nan)
        uvk = np.where(np.isnan(uv), np.inf, uv)
        order = np.lexsort((rows, uvk, key, group))
        gs = group[order]
        first = np.r_[True, gs[1:] != gs[:-1]] if len(gs) else np.zeros(0, bool)
        pick = order[first]
        gid = group[pick]
        best = np.full(G, EMPTY, dtype=np.int8)
        best[gid] = code[pick]
        out[f] = best
        ub = np.full(G, np.nan)
        ub[gid] = uv[pick]
        out[f"uv_{f}"] = ub
        src = np.full(G, -1, dtype=np.int64)
        src[gid] = pick
        out[f"src_{f}"] = src
        if f"veto_{f}" in lv:
            v = lv[f"veto_{f}"].to_numpy(dtype=bool)
            anyv = np.bincount(group, weights=v.astype(float), minlength=G) > 0
            anyx = np.bincount(group, weights=(code == 0).astype(float), minlength=G) > 0
            out[f"veto_{f}"] = anyv & ~anyx
        if k is not None and f in k:
            out[f"k_{f}"] = np.asarray(k[f], dtype=float)
    return pd.DataFrame(out)


def _values_conflict(field_, a, b):
    """Two value sets of a one-per-party identifier conflict when together they hold two
    different values; driver licences only within one state."""
    u = set(a) | set(b)
    if field_ == "dl":
        by = defaultdict(set)
        for v in u:
            st, _, num = v.partition(":")
            if st:
                by[st].add(num)
        return any(len(s) > 1 for s in by.values())
    return len(u) > 1


def constrained_clusters(n, a, b, p, node_values, fields=VETO_FIELDS):
    """Greedy agglomeration with cannot-link constraints. Edges (a[i], b[i]) are taken best
    first (p descending, then a, b); two clusters merge only when no field in `fields` would
    then hold conflicting values (`node_values[field][node]`: a set of single-holder values).
    Transitive by construction; a refused edge keeps the field that refused it.
    Returns (cluster id per node: its smallest node index, accepted mask, refusal reason)."""
    parent = np.arange(n)
    vals = {}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def values(r):
        if r not in vals:
            vals[r] = {f: set(node_values[f][r]) if f in node_values else set() for f in fields}
        return vals[r]
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    p = np.asarray(p, dtype=float)
    order = np.lexsort((b, a, -p))
    accepted = np.zeros(len(a), dtype=bool)
    reason = np.full(len(a), "", dtype=object)
    size = np.ones(n, dtype=np.int64)
    for i in order:
        ra, rb = find(a[i]), find(b[i])
        if ra == rb:
            accepted[i] = True
            continue
        va, vb = values(ra), values(rb)
        bad = [f for f in fields if va[f] and vb[f] and _values_conflict(f, va[f], vb[f])]
        if bad:
            reason[i] = "conflicting " + "+".join(bad)
            continue
        if size[ra] < size[rb]:
            ra, rb, va, vb = rb, ra, vb, va
        parent[rb] = ra
        size[ra] += size[rb]
        for f in fields:
            va[f] |= vb[f]
        vals.pop(rb, None)
        accepted[i] = True
    roots = np.array([find(i) for i in range(n)], dtype=np.int64)
    first = pd.Series(np.arange(n)).groupby(roots).transform("min").to_numpy()
    return first, accepted, reason
