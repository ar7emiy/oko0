DISPLAY = {"name": lambda F: (F["first"] + " " + F["last"]).str.strip(), "middle": lambda F: F["middle"],
           "org": lambda F: F["org_aliases"].str.replace("|", " / ", regex=False), "dob": lambda F: F["dob"],
           "address": lambda F: F["raw_address"], "phone": lambda F: (F["phone_own"] + " " + F["phone_row"]).str.strip(),
           "spec_cat": lambda F: (F["specialty"] + " / " + F["category"]).str.strip(" /"),
           "co_party": lambda F: F["tie"]}


def evidence_for(pr, part, pairs_part, levels_part, S_part, weights):
    """Evidence rows of kept entity pairs: the extracted value is the one the member that
    supplied the field's best level holds (its record id in `extracted_record_id`)."""
    X, W = pr.X[part], pr.W[part]
    r = S_part["r"].to_numpy(dtype=np.int64)
    vl, vr, src_rid = {}, {}, {}
    rid = X["record_id"].to_numpy(dtype=object)
    for f in PART_FIELDS[part]:
        src = levels_part[f"src_{f}"].to_numpy(dtype=np.int64) if f"src_{f}" in levels_part else np.full(len(r), -1)
        ok = src >= 0
        s0 = np.maximum(src, 0)
        if f in DISPLAY:
            xl = DISPLAY[f](X).to_numpy(dtype=object)
            vl[f] = np.where(ok, xl[s0] if len(xl) else "", "")
            vr[f] = DISPLAY[f](W).to_numpy(dtype=object)[r]
        elif f"id_{f}" in X:
            xl = X[f"id_{f}"].to_numpy(dtype=object)
            vl[f] = np.where(ok, xl[s0] if len(xl) else "", "")
            vr[f] = W[f"id_{f}"].to_numpy(dtype=object)[r]
        src_rid[f] = np.where(ok, rid[s0] if len(rid) else "", "")
    ev = evidence_rows(pairs_part["pair_id"].to_numpy(), levels_part, S_part, part, weights, vl, vr)
    if len(ev):
        pos = pd.Series(np.arange(len(pairs_part)), index=pairs_part["pair_id"].to_numpy())
        i = pos.reindex(ev["pair_id"]).to_numpy()
        ev.insert(2, "extracted_record_id", [src_rid[f][j] for f, j in zip(ev["field"], i)])
    return ev


def decision_cards(evidence, pair_ids=None, max_fields=12):
    """One compact line per pair: field level (bits), strongest first, e.g.
    'ssn exact +19.3; name first_close +11.2; dob differs -5.1'."""
    ev = evidence if pair_ids is None else evidence[evidence["pair_id"].isin(set(pair_ids))]
    if not len(ev):
        return pd.Series(dtype=object)
    ev = ev.assign(_a=-ev["bits"].abs()).sort_values(["pair_id", "_a"], kind="stable")
    txt = ev["field"] + " " + ev["level"] + " " + ev["bits"].map(lambda b: f"{b:+.1f}") + \
        np.where(ev["veto"].astype(bool), " VETO", "")
    return txt.groupby(ev["pair_id"].to_numpy()).agg(lambda s: "; ".join(list(s)[:max_fields]))


def sensitivity(entities_best, prior_df, cfg):
    """How many entities cross 0.5 / 0.8 / 0.9 if the prior or the recall behind it moved."""
    rows = []
    for _, pr_ in prior_df.iterrows():
        sub = entities_best[(entities_best["part"] == pr_["part"]) & (entities_best["prior_group"] == pr_["group"])]
        bits = sub["bits"].to_numpy()
        for mult in cfg.sensitivity_prior_mult:
            for rmult in cfg.sensitivity_recall:
                rec = min(1.0, pr_["recall"] * rmult) if pr_["recall"] > 0 else 0.0
                base = pr_["prior"] * mult * (pr_["recall"] / rec if rec > 0 else 1.0)
                base = min(base, 0.5)
                logit = math.log2(base / (1 - base)) + bits
                p = 1 / (1 + np.exp2(-logit))
                row = {"part": pr_["part"], "group": pr_["group"], "prior_multiplier": mult,
                       "recall_multiplier": rmult, "prior": base, "entities": len(sub)}
                for t in cfg.p_bands:
                    row[f"entities_p>={t}"] = int((p >= t).sum())
                rows.append(row)
    return pd.DataFrame(rows)