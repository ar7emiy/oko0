def pair_table(pr, part, S, ent, status=None, e_cid=None, w_cid=None):
    """Kept entity x watchlist pairs with identities, names, ranking and cluster status."""
    if not len(S):
        return pd.DataFrame()
    X, W = pr.X[part], pr.W[part]
    e, r = S["e"].to_numpy(dtype=np.int64), S["r"].to_numpy(dtype=np.int64)
    first = ent.order[ent.start[e]]                     # a member for display
    out = pd.DataFrame({
        "pair_id": ent.ids[e] + "~" + W["party_id"].to_numpy()[r],
        "entity_id": ent.ids[e], "part": part, "entity_records": ent.size[e],
        "extracted_record_id": X["record_id"].to_numpy()[first],
        "claim_id": X["claim_id"].to_numpy()[first], "extracted_name": X["display_name"].to_numpy()[first],
        "watchlist_record_id": W["record_id"].to_numpy()[r], "watchlist_name": W["display_name"].to_numpy()[r],
        "p": S["p"].to_numpy(), "bits": S["bits"].to_numpy(), "prior_bits": S["prior_logit"].to_numpy(),
        "basis": S["basis"].to_numpy(), "rests_on_name": np.isin(S["basis"].to_numpy(), ["contextual", "name_only"]),
        "veto": S["veto"].to_numpy(), "rank": S["rank"].to_numpy(), "proposed_by": S["rules"].to_numpy(),
        "cluster_status": status if status is not None and len(status) == len(S) else "",
        "cluster_id": (np.array([f"C{part[0].upper()}{x}" for x in e_cid[e]], dtype=object) if e_cid is not None else ""),
        "_e": e, "_r": r})
    for f in PART_FIELDS[part]:
        out[f"bits_{f}"] = S[f"bits_{f}"].to_numpy()
    return out


def _listing(df, what):
    """'W1 (0.97, identifier); W2 (...)' per entity (_e)."""
    if not len(df):
        return pd.Series(dtype=object)
    txt = [f"{w} ({p:.3g}, {b})" for w, p, b in zip(df["watchlist_record_id"], df["p"], df[what])]
    return pd.Series(txt, index=df.index).groupby(df["_e"].to_numpy()).agg("; ".join)


def rollup_entities(pr, pairs, E_by_part, ents, clusters, cfg):
    """One row per extracted entity. Its p is its best link inside its cluster (consistent
    watchlist records only) or, without a cluster, its best candidate; its status says which;
    conflicting candidates are listed apart; every other candidate is listed."""
    out = []
    for part in ("person", "business"):
        X, W = pr.X[part], pr.W[part]
        ent = ents[part]
        E = len(ent.ids)
        Es = E_by_part[part]
        first = ent.order[ent.start[:-1]] if E else np.array([], np.int64)
        members_rid = pd.Series(X["record_id"].to_numpy()[ent.order]).groupby(ent.e_of[ent.order]).agg("; ".join)
        claims = pd.Series(X["claim_id"].to_numpy()[ent.order]).groupby(ent.e_of[ent.order]).agg(
            lambda s: "; ".join(sorted({x for x in s if x})))
        base = pd.DataFrame({
            "entity_id": ent.ids, "part": part, "records": ent.size,
            "record_ids": members_rid.reindex(np.arange(E)).fillna("").to_numpy(),
            "claim_ids": claims.reindex(np.arange(E)).fillna("").to_numpy(),
            "name": X["display_name"].to_numpy()[first] if E else [],
            "category_given": X["category_given"].to_numpy()[first] if E else [],
            "category_inferred": X["category_inferred"].to_numpy()[first] if E else [],
            "category_used": X["category"].to_numpy()[first] if E else [],
            "category_mismatch": (pd.Series(X["category_mismatch"].to_numpy()[ent.order]).groupby(ent.e_of[ent.order]).any()
                                  .reindex(np.arange(E)).fillna(False).to_numpy()),
            "prior_group": entity_prior_group(X, ent) if E else [],
            "dedup_weakest_p": ent.weakest})
        idx = np.arange(E)
        base["candidates"] = Es["candidates"].reindex(idx).fillna(0).astype(int).to_numpy() if len(Es) else 0
        base["vetoed_candidates"] = Es["vetoed"].reindex(idx).fillna(0).astype(int).to_numpy() if len(Es) else 0
        e_cid = clusters[part]["e_cid"]
        w_cid = clusters[part]["w_cid"]
        base["cluster_id"] = [f"C{part[0].upper()}{c}" for c in e_cid]
        in_cl = pd.Series(W["record_id"].to_numpy()).groupby(w_cid).agg(lambda s: "; ".join(sorted(s))) if len(W) else pd.Series(dtype=object)
        base["cluster_watchlist_ids"] = pd.Series(e_cid).map(in_cl).fillna("").to_numpy()
        P = pairs[pairs["part"] == part] if len(pairs) else pd.DataFrame()
        cols = dict(best_watchlist_record_id="", best_watchlist_name="", p=0.0, basis="none", match_status="",
                    best_non_name_p=0.0, other_candidates="", conflicting_candidates="", cluster_weakest_p=np.nan)
        for c, v in cols.items():
            base[c] = v
        if len(P):
            ok = P[P["veto"] == ""].sort_values(["_e", "p", "bits", "watchlist_record_id"],
                                                ascending=[True, False, False, True], kind="stable")
            linked = ok[ok["cluster_status"] == "linked"]
            best_l = linked.groupby("_e").head(1).set_index("_e")
            best_a = ok.groupby("_e").head(1).set_index("_e")
            best = best_a.copy()
            best.loc[best_l.index] = best_l
            best["match_status"] = np.where(best.index.isin(best_l.index), "linked in a consistent cluster",
                                            best["cluster_status"].to_numpy())
            non_name = ok[~ok["rests_on_name"] & (ok["basis"] != "none")].groupby("_e")["p"].max()
            conf = ok[ok["cluster_status"].astype(str).str.startswith("conflict")]
            conf_txt = _listing(conf, "cluster_status")
            best_r = best["watchlist_record_id"]
            rest = ok[ok["watchlist_record_id"].to_numpy() != best_r.reindex(ok["_e"]).to_numpy()]
            pos = rest.groupby("_e").cumcount().to_numpy()
            others = _listing(rest[pos < cfg.top_k], "basis")
            weak = linked.groupby("_e")["p"].min()
            base["best_watchlist_record_id"] = best["watchlist_record_id"].reindex(idx).fillna("").to_numpy()
            base["best_watchlist_name"] = best["watchlist_name"].reindex(idx).fillna("").to_numpy()
            base["p"] = best["p"].reindex(idx).fillna(0.0).to_numpy()
            base["basis"] = best["basis"].reindex(idx).fillna("none").to_numpy()
            base["match_status"] = best["match_status"].reindex(idx).fillna("").to_numpy()
            base["best_non_name_p"] = non_name.reindex(idx).fillna(0.0).to_numpy()
            base["other_candidates"] = others.reindex(idx).fillna("").to_numpy()
            base["conflicting_candidates"] = conf_txt.reindex(idx).fillna("").to_numpy()
            base["cluster_weakest_p"] = weak.reindex(idx).to_numpy()
        base["rests_on_name"] = np.isin(base["basis"].to_numpy(), ["contextual", "name_only"])
        base.loc[base["best_watchlist_record_id"] == "", "cluster_watchlist_ids"] = ""
        base["status"] = np.where(base["candidates"] == 0, "no candidate proposed",
                                  np.where(base["best_watchlist_record_id"] == "", "only vetoed candidates", "scored"))
        base["_e"] = idx
        out.append(base)
    return pd.concat(out, ignore_index=True)


def rollup_rows(pr, entities, ents):
    """One row per extracted party (record_id + part), pointing back to its entity's result."""
    out = []
    for part in ("person", "business"):
        X = pr.X[part]
        ent = ents[part]
        E = entities[entities["part"] == part].set_index("_e")
        e = ent.e_of
        d = pd.DataFrame({"party_id": X["party_id"], "record_id": X["record_id"], "part": part,
                          "claim_id": X["claim_id"], "note_id": X["note_id"], "name": X["display_name"],
                          "entity_id": ent.ids[e], "entity_records": ent.size[e]})
        for c in ("best_watchlist_record_id", "best_watchlist_name", "p", "basis", "rests_on_name", "match_status",
                  "cluster_id", "cluster_watchlist_ids", "status", "category_used", "prior_group"):
            d[c] = E[c].reindex(e).to_numpy()
        out.append(d)
    return pd.concat(out, ignore_index=True)


def p_band(p):
    return np.select([p >= 0.9, p >= 0.8, p >= 0.5, p >= 0.1], ["p>=0.9", "0.8-0.9", "0.5-0.8", "0.1-0.5"], "p<0.1")


def rollup_claims(rows, xrows_claims):
    """Per claim: rows, parties, the highest p and its party, counts by basis x p band."""
    e = rows.copy()
    e["band"] = p_band(e["p"].to_numpy())
    g = e.groupby("claim_id", sort=True)
    top = e.sort_values(["claim_id", "p"], ascending=[True, False], kind="stable").groupby("claim_id").head(1).set_index("claim_id")
    out = pd.DataFrame({"rows": xrows_claims.reindex(g.size().index).fillna(0).astype(int),
                        "parties": g.size(), "entities": g["entity_id"].nunique(), "max_p": g["p"].max()})
    out["max_p_party"] = top["party_id"].reindex(out.index)
    out["max_p_name"] = top["name"].reindex(out.index)
    out["max_p_basis"] = top["basis"].reindex(out.index)
    ct = pd.crosstab(e["claim_id"], e["basis"] + " " + e["band"])
    out = out.join(ct, how="left").fillna(0)
    out["name_only_at_p_0.5"] = e[(e["basis"] == "name_only") & (e["p"] >= 0.5)].groupby("claim_id").size().reindex(out.index).fillna(0).astype(int)
    return out.reset_index().rename(columns={"index": "claim_id"})


def dedup_table(pr, dd, ents):
    """Kept extracted x extracted pairs, with whether they pooled."""
    out = []
    for part in ("person", "business"):
        D = dd[part][0]
        if not len(D):
            continue
        X = pr.X[part]
        l, r = D["l"].to_numpy(dtype=np.int64), D["r"].to_numpy(dtype=np.int64)
        ent = ents[part]
        out.append(pd.DataFrame({
            "part": part, "record_id_1": X["record_id"].to_numpy()[l], "record_id_2": X["record_id"].to_numpy()[r],
            "name_1": X["display_name"].to_numpy()[l], "name_2": X["display_name"].to_numpy()[r],
            "claim_1": X["claim_id"].to_numpy()[l], "claim_2": X["claim_id"].to_numpy()[r],
            "p": D["p"].to_numpy(), "bits": D["bits"].to_numpy(), "basis": D["basis"].to_numpy(),
            "veto": D["veto"].to_numpy(), "proposed_by": D["rules"].to_numpy(),
            "same_entity": ent.e_of[l] == ent.e_of[r], "entity_id": np.where(ent.e_of[l] == ent.e_of[r], ent.ids[ent.e_of[l]], "")}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()
