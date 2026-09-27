P_BINS = np.array([0, 1e-3, 0.01, 0.1, 0.5, 0.8, 0.9, 0.99, 1.0000001])
DEDUP_KEEP_P = 0.05          # dedup pairs kept for display below the pooling threshold


def _rank_within(l, p):
    """Rank of each pair within its entity (l), best first; ties share the rank ('min')."""
    d = pd.DataFrame({"l": l, "p": p})
    return d.groupby("l")["p"].rank(method="min", ascending=False).to_numpy()


def _key(a, b):
    return np.asarray(a, dtype=np.int64) * np.int64(1 << 32) + np.asarray(b, dtype=np.int64)


def single_values(frame, stats, fields=VETO_FIELDS):
    """Per party, the single-holder values of the one-per-party identifiers (for vetoes and
    cluster constraints): {field: list of frozensets}."""
    out = {}
    for f in fields:
        col = f"id_{f}"
        s = stats.single.get(f, set())
        v = frame[col].to_numpy(dtype=object) if col in frame else np.full(len(frame), "", dtype=object)
        out[f] = [frozenset([x]) if (x and x in s) else frozenset() for x in v]
    return out


# ---- 12a deduplication: extracted x extracted --------------------------------------------------
def score_dedup_part(pr, part, model, cfg, anchors=None, log=print):
    """Score every candidate pair of extracted parties of one part (each unordered pair once).
    Returns (kept pairs with levels, diagnostics)."""
    X = pr.X[part]
    ctx = pr.ctx_dedup
    plan = CandidatePlan(X, X, part, ctx.rarity, cfg, ctx.dba_pairs, same_frame=True)
    logit = math.log2(model.prior[(part, "all")] / (1 - model.prior[(part, "all")])) if (part, "all") in model.prior else 0.0
    kept, n_scored = [], 0
    for lo, hi in plan.chunks():
        c = plan.chunk(lo, hi)
        if not len(c):
            continue
        l, r = c["l"].to_numpy(), c["r"].to_numpy()
        lv = compare_pairs(X, X, l, r, part, ctx)
        pl = np.full(len(lv), logit)
        if part == "person":
            tl, tr = X["tie_pos"].to_numpy()[l], X["tie_pos"].to_numpy()[r]
            has = (tl >= 0) & (tr >= 0)
            lv["co_party"] = np.where(has, 1, EMPTY).astype(np.int8)
            sc = score_pairs(lv, part, model.weights[part], pl, cfg.core)
            anch = np.zeros(len(lv), bool)
            if anchors is not None and len(anchors) and has.any():
                anch[has] = np.isin(_key(np.minimum(tl[has], tr[has]), np.maximum(tl[has], tr[has])), anchors)
            if anch.any():
                lv, sc = apply_coparty(lv, sc, model.weights[part], pl, anch, cfg.core)
        else:
            sc = score_pairs(lv, part, model.weights[part], pl, cfg.core)
        n_scored += len(sc)
        p = sc["p"].to_numpy()
        keep = (p >= DEDUP_KEEP_P) | (sc["veto"].to_numpy() != "") | (sc["basis"].to_numpy() == "identifier")
        s = pd.concat([lv[keep].reset_index(drop=True),
                       sc[keep].reset_index(drop=True)[[c_ for c_ in sc.columns]]], axis=1)
        s["rules"] = plan.rule_names(c["rules"].to_numpy()[keep])
        kept.append(s)
    D = pd.concat(kept, ignore_index=True) if kept else pd.DataFrame(columns=["l", "r", "p", "veto", "basis", "bits"])
    log(f"  dedup {part}: {n_scored:,} extracted pairs scored, {len(D):,} kept")
    return D, {"scored": n_scored, "report": plan.report}


def dedup_anchors(D, cfg):
    """Business dedup pairs linked on an identifier (p >= coparty_min_p, no veto): co-party
    anchors for the person dedup pass."""
    if not len(D):
        return np.array([], np.int64)
    m = (D["basis"] == "identifier") & (D["p"] >= cfg.core.coparty_min_p) & (D["veto"] == "")
    return np.unique(_key(D.loc[m, "l"], D.loc[m, "r"]))


@dataclass
class Entities:
    """Extracted parties of one part pooled into entities (deduplication)."""
    part: str
    e_of: np.ndarray       # party position -> entity index
    order: np.ndarray      # party positions sorted by entity
    start: np.ndarray      # entity e's members are order[start[e]:start[e + 1]]
    ids: np.ndarray        # entity id per entity
    size: np.ndarray
    weakest: np.ndarray    # weakest accepted dedup link inside the entity (nan: a single record)
    refused: int           # dedup links refused because the result would hold conflicting identifiers
    k: dict                # field -> distinct values the entity offers, per entity

    def members(self, e):
        return self.order[self.start[e]:self.start[e + 1]]


K_KEYS = {"name": ["first", "last"], "middle": ["middle"], "dob": ["dob"], "address": ["addr_full", "addr_street", "city_state", "state"],
          "phone": ["phone_own", "phone_row"], "spec_cat": ["specialty", "category"], "org": ["org_aliases"],
          **{f: [f"id_{f}"] for f in ["ssn", "npi", "dl", "tin", "license", "email", "vin", "plate", "cnpi"]}}


def build_entities(pr, part, D, cfg):
    """Pool extracted parties: accepted dedup links (p >= dedup_p_min, no veto, a basis in
    dedup_basis) joined by constrained union-find, never pooling two different single-holder
    identifiers of one kind."""
    X = pr.X[part]
    n = len(X)
    if len(D):
        ok = (D["p"].to_numpy() >= cfg.dedup_p_min) & (D["veto"].to_numpy() == "") & \
             np.isin(D["basis"].to_numpy(), list(cfg.dedup_basis))
        a, b, p = D["l"].to_numpy()[ok], D["r"].to_numpy()[ok], D["p"].to_numpy()[ok]
    else:
        a = b = np.array([], np.int64); p = np.array([], float)
    cid, acc, why = constrained_clusters(n, a, b, p, single_values(X, pr.ctx.stats))
    uniq, e_of = np.unique(cid, return_inverse=True)
    order = np.argsort(e_of, kind="stable")
    size = np.bincount(e_of, minlength=len(uniq))
    start = np.r_[0, np.cumsum(size)]
    weakest = np.full(len(uniq), np.nan)
    if acc.any():
        ea = e_of[a[acc]]
        w = pd.Series(p[acc]).groupby(ea).min()
        weakest[w.index.to_numpy()] = w.to_numpy()
    rid = X["record_id"].to_numpy(dtype=object)
    first_rid = pd.Series(rid[order]).groupby(e_of[order]).min().to_numpy()
    ids = np.array([f"XE:{r}:{'P' if part == 'person' else 'B'}" for r in first_rid], dtype=object)
    k = {}
    for f, cols in K_KEYS.items():
        cols = [c for c in cols if c in X]
        if not cols:
            continue
        key = X[cols[0]].to_numpy(dtype=object).copy()
        if f in ("address",):                       # the most specific address key a party has
            for c in cols[1:]:
                key = np.where(key != "", key, X[c].to_numpy(dtype=object))
        elif f == "phone":
            key = np.where(X["phone_own"] != "", X["phone_own"], X["phone_row"])
        elif len(cols) > 1:
            for c in cols[1:]:
                key = key + "|" + X[c].to_numpy(dtype=object)
            key = np.where(np.char.str_len(key.astype(str)) > len(cols) - 1, key, "")
        d = pd.DataFrame({"e": e_of, "v": key})
        d = d[d["v"] != ""]
        k[f] = np.maximum(1, d.groupby("e")["v"].nunique().reindex(np.arange(len(uniq))).fillna(0).to_numpy())
    return Entities(part=part, e_of=e_of, order=order, start=start, ids=ids, size=size, weakest=weakest,
                    refused=int((~acc & (why != "")).sum()), k=k)


def entity_prior_group(X, ent):
    """An entity's prior group: professional if any member is, else business, private, unknown."""
    rank = {"professional": 0, "business": 1, "private": 2, "unknown": 3}
    g = X["prior_group"].map(rank).fillna(3).to_numpy()
    best = pd.Series(g).groupby(ent.e_of).min().reindex(np.arange(len(ent.ids))).fillna(3).to_numpy()
    inv = {v: k for k, v in rank.items()}
    return np.array([inv[int(x)] for x in best], dtype=object)


# ---- 12b linking: extracted entities x watchlist -----------------------------------------------
def score_link_part(pr, part, ent, model, cfg, anchors=None, log=print, only_entities=None):
    """Score every candidate (entity, watchlist party) of one part: candidates proposed by any
    member; every member compared with every candidate of its entity; per field the best level
    of any member (aggregate_member_levels), with the multiplicity correction; co-party through
    the members' tied businesses. `only_entities`: score just these (incremental runs).
    Returns (kept scores, kept aggregated levels, per-entity summary, diagnostics)."""
    X, W = pr.X[part], pr.W[part]
    ctx = pr.ctx
    plan = CandidatePlan(X, W, part, ctx.rarity, cfg, ctx.dba_pairs)
    for rep in plan.report:
        log(f"  {part:<8} {rep['rule']:<24} pairs {rep['pairs_before_refine']:>12,}"
            + (f"  oversized keys {rep['oversized_keys']} -> dropped {rep['dropped_keys']} ({rep['dropped_pairs']:,} pairs)"
               if rep['oversized_keys'] or rep['dropped_keys'] else ""))
    grp_logit = {g: math.log2(model.prior[(part, g)] / (1 - model.prior[(part, g)])) for g in GROUPS if (part, g) in model.prior}
    e_group = entity_prior_group(X, ent)
    e_logit = pd.Series(e_group).map(grp_logit).fillna(0.0).to_numpy(dtype=float)
    E = len(ent.ids)
    ents = np.arange(E) if only_entities is None else np.unique(np.asarray(only_entities, dtype=np.int64))
    kept_s, kept_l, summ, all_keys = [], [], [], []
    hist = np.zeros((len(BASIS_ORDER), len(P_BINS) - 1), dtype=np.int64)
    n_scored, n_member_pairs = 0, 0
    rule_counts = defaultdict(int)
    fields = COMPARED_FIELDS[part] + (["co_party"] if part == "person" else [])
    # chunks of entities holding about chunk_size members (exhaustive: a pair budget)
    budget = cfg.chunk_size if not plan.exhaustive else max(1, cfg.exhaustive_pairs_per_chunk // max(1, len(W)))
    sizes = ent.size[ents]
    cuts = [0]
    acc_ = 0
    for i, s_ in enumerate(sizes):
        acc_ += s_
        if acc_ >= budget:
            cuts.append(i + 1); acc_ = 0
    if cuts[-1] != len(ents):
        cuts.append(len(ents))
    tie_x, tie_w = X["tie_pos"].to_numpy(), W["tie_pos"].to_numpy()
    for ci in range(len(cuts) - 1):
        ce = ents[cuts[ci]:cuts[ci + 1]]
        mpos = np.concatenate([ent.members(e) for e in ce]) if len(ce) else np.array([], np.int64)
        c = plan.chunk_positions(mpos)
        if not len(c):
            continue
        e = ent.e_of[c["l"].to_numpy()]
        ek = _key(e, c["r"].to_numpy())
        order = np.argsort(ek, kind="stable")
        ek_s, b_s = ek[order], c["rules"].to_numpy()[order]
        st = np.flatnonzero(np.r_[True, ek_s[1:] != ek_s[:-1]])
        uk = ek_s[st]
        rules = np.bitwise_or.reduceat(b_s, st)
        ce_e, ce_r = (uk >> 32).astype(np.int64), (uk & np.int64((1 << 32) - 1)).astype(np.int64)
        all_keys.append(uk)
        for name, bit in plan.bit.items():
            rule_counts[name] += int(((rules & bit) > 0).sum())
        # expand to every member of the entity
        n_e = ent.size[ce_e]
        g = np.repeat(np.arange(len(ce_e)), n_e)
        offs = np.arange(len(g)) - np.repeat(np.cumsum(n_e) - n_e, n_e)
        m = ent.order[ent.start[ce_e][g] + offs]
        r_m = ce_r[g]
        lv = compare_pairs(X, W, m, r_m, part, ctx)
        n_member_pairs += len(lv)
        if part == "person":
            tl, tr = tie_x[m], tie_w[r_m]
            has = (tl >= 0) & (tr >= 0)
            code = np.where(has, 1, EMPTY)
            if anchors is not None and len(anchors) and has.any():
                eb = np.full(len(tl), -1, dtype=np.int64)
                eb[has] = anchors["e_of_business"][tl[has]]
                code = np.where(has & np.isin(_key(np.maximum(eb, 0), np.maximum(tr, 0)), anchors["keys"]), 0, code)
            lv["co_party"] = code.astype(np.int8)
            lv["uv_co_party"] = np.nan
        kk = {f: ent.k[f][ce_e] for f in ent.k if f in fields}
        agg = aggregate_member_levels(lv, g, fields, kk)
        pl = e_logit[ce_e]
        if part == "person":
            anchored = agg["co_party"].to_numpy() == 0
            agg["co_party"] = np.where(agg["co_party"].to_numpy() >= 0, 1, EMPTY).astype(np.int8)
            sc = score_pairs(agg, part, model.weights[part], pl, cfg.core)
            if anchored.any():
                agg, sc = apply_coparty(agg, sc, model.weights[part], pl, anchored, cfg.core)
        else:
            sc = score_pairs(agg, part, model.weights[part], pl, cfg.core)
        # the member that supplied each field's best level: a party position
        for f in fields:
            if f"src_{f}" in agg:
                s_ = agg[f"src_{f}"].to_numpy()
                agg[f"src_{f}"] = np.where(s_ >= 0, m[np.maximum(s_, 0)], -1)
        n_scored += len(sc)
        p = sc["p"].to_numpy()
        basis = sc["basis"].to_numpy()
        bi = pd.Series(basis).map({b: i for i, b in enumerate(BASIS_ORDER)}).to_numpy()
        pbin = np.clip(np.searchsorted(P_BINS, p, side="right") - 1, 0, len(P_BINS) - 2)
        vetoed = sc["veto"].to_numpy() != ""
        np.add.at(hist, (bi[~vetoed], pbin[~vetoed]), 1)
        rank = _rank_within(ce_e, np.where(vetoed, -1.0, p))
        keep = (p >= cfg.keep_p_floor) | (rank <= cfg.top_k) | (basis == "identifier") | vetoed
        s = sc[keep].copy()
        s.insert(0, "rank", np.where(vetoed[keep], np.nan, rank[keep]))
        s.insert(0, "rules", plan.rule_names(rules[keep]))
        s.insert(0, "r", ce_r[keep]); s.insert(0, "e", ce_e[keep])
        s["prior_logit"] = pl[keep]
        kept_s.append(s.reset_index(drop=True))
        kept_l.append(agg[keep].reset_index(drop=True))
        summ.append(pd.DataFrame({"e": ce_e, "veto": vetoed}).groupby("e").agg(candidates=("veto", "size"),
                                                                              vetoed=("veto", "sum")))
    S = pd.concat(kept_s, ignore_index=True) if kept_s else pd.DataFrame(columns=["e", "r", "rules", "rank", "p", "veto", "basis", "bits"])
    L = pd.concat(kept_l, ignore_index=True) if kept_l else pd.DataFrame()
    if len(S):                      # a fixed order: (entity, watchlist party)
        order = np.lexsort((S["r"].to_numpy(), S["e"].to_numpy()))
        S, L = S.iloc[order].reset_index(drop=True), L.iloc[order].reset_index(drop=True)
    Es = pd.concat(summ).sort_index() if summ else pd.DataFrame(columns=["candidates", "vetoed"])
    keys = np.concatenate(all_keys) if all_keys else np.array([], np.int64)
    diag = {"hist": hist, "scored": n_scored, "member_pairs": n_member_pairs, "rule_counts": dict(rule_counts),
            "report": plan.report, "keys": keys, "exhaustive": plan.exhaustive}
    log(f"  link {part}: {n_scored:,} entity x watchlist pairs scored ({n_member_pairs:,} member comparisons), "
        f"{len(S):,} kept")
    return S, L, Es, diag


def link_anchors(S_business, ent_business, cfg):
    """Business entity x watchlist links on an identifier (p >= coparty_min_p, no veto): the
    co-party anchors of the person pass, keyed (business entity, watchlist business)."""
    keys = np.array([], np.int64)
    if len(S_business):
        m = (S_business["basis"] == "identifier") & (S_business["p"] >= cfg.core.coparty_min_p) & (S_business["veto"] == "")
        keys = np.unique(_key(S_business.loc[m, "e"], S_business.loc[m, "r"]))
    return {"keys": keys, "e_of_business": ent_business.e_of}


# ---- 12c consistent clusters -----------------------------------------------------------------
def link_clusters(pr, part, ent, S, cfg):
    """Entities and watchlist parties joined by links at p >= link_cluster_p that rest on more
    than a name, by constrained union-find: transitive, and never holding two different
    single-holder values of SSN / NPI / DL (one state) / TIN, so no entity is half-matched to
    contradictory watchlist records. Name-only links stay visible and are labelled, but never
    join a cluster. Returns (pair status array, cluster id per entity, cluster frame)."""
    X, W = pr.X[part], pr.W[part]
    E, NW = len(ent.ids), len(W)
    xv = single_values(X, pr.ctx.stats)
    wv = single_values(W, pr.ctx.stats)
    node_vals = {}
    for f in VETO_FIELDS:
        ev = [set() for _ in range(E)]
        for pos, vals in enumerate(xv[f]):
            if vals:
                ev[ent.e_of[pos]] |= vals
        node_vals[f] = [frozenset(s) for s in ev] + list(wv[f])
    if len(S):
        p = S["p"].to_numpy(dtype=float)
        veto = S["veto"].to_numpy() != ""
        basis = S["basis"].to_numpy()
        on_name = np.isin(basis, ["contextual", "name_only", "none"])
        edge = (p >= cfg.link_cluster_p) & ~veto & ~on_name
        a = S["e"].to_numpy(dtype=np.int64)[edge]
        b = E + S["r"].to_numpy(dtype=np.int64)[edge]
        cid, acc, why = constrained_clusters(E + NW, a, b, p[edge], node_vals)
        status = np.full(len(S), "below threshold", dtype=object)
        status[veto] = "vetoed"
        status[(p >= cfg.link_cluster_p) & ~veto & on_name] = "name only: visible, not clustered"
        st_e = np.where(acc, "linked", "conflict: " + why.astype(str))
        status[np.flatnonzero(edge)] = st_e
        same = cid[S["e"].to_numpy(dtype=np.int64)] == cid[E + S["r"].to_numpy(dtype=np.int64)]
        status[same & (status == "below threshold")] = "same cluster (weak direct link)"
    else:
        cid = np.arange(E + NW)
        status = np.array([], dtype=object)
    return status, cid[:E], cid[E:]


def score_all(pr, models, cfg, log=print, cache=None):
    """Deduplication (businesses first: their identifier links anchor the persons' co-party),
    entities, linking, clusters. `cache`: a LinkCache (incremental runs, section 15b)."""
    res = {"dedup": {}, "entities": {}, "link": {}, "clusters": {}}
    D_b, dd_b = score_dedup_part(pr, "business", models["dedup"], cfg, log=log)
    D_p, dd_p = score_dedup_part(pr, "person", models["dedup"], cfg, anchors=dedup_anchors(D_b, cfg), log=log)
    res["dedup"] = {"business": (D_b, dd_b), "person": (D_p, dd_p)}
    for part, D in (("business", D_b), ("person", D_p)):
        ent = build_entities(pr, part, D, cfg)
        res["entities"][part] = ent
        log(f"  entities [{part}]: {len(pr.X[part]):,} extracted parties -> {len(ent.ids):,} entities "
            f"({int((ent.size > 1).sum()):,} pooled, largest {int(ent.size.max()) if len(ent.size) else 0}); "
            f"{ent.refused} dedup links refused (conflicting identifiers)")
    eb, ep = res["entities"]["business"], res["entities"]["person"]
    if cache is None:
        Sb, Lb, Eb, Db = score_link_part(pr, "business", eb, models["link"], cfg, log=log)
    else:
        Sb, Lb, Eb, Db = score_link_cached(pr, "business", eb, models["link"], cfg, cache, log=log)
    anchors = link_anchors(Sb, eb, cfg)
    log(f"  co-party anchors (business entities linked on an identifier, p >= {cfg.core.coparty_min_p}): {len(anchors['keys'])}")
    if cache is None:
        Sp, Lp, Ep, Dp = score_link_part(pr, "person", ep, models["link"], cfg, anchors=anchors, log=log)
    else:
        tied = cache.sigs["business"][eb.e_of] if len(eb.e_of) else np.array([], dtype=object)
        Sp, Lp, Ep, Dp = score_link_cached(pr, "person", ep, models["link"], cfg, cache, tied=tied, anchors=anchors, log=log)
    res["link"] = {"business": (Sb, Lb, Eb, Db), "person": (Sp, Lp, Ep, Dp)}
    for part in ("business", "person"):
        S = res["link"][part][0]
        status, e_cid, w_cid = link_clusters(pr, part, res["entities"][part], S, cfg)
        res["clusters"][part] = {"status": status, "e_cid": e_cid, "w_cid": w_cid}
        if len(S):
            vc = pd.Series(status).map(lambda s: s.split(":")[0]).value_counts().to_dict()
            log(f"  clusters [{part}]: pair status {vc}")
    return res
