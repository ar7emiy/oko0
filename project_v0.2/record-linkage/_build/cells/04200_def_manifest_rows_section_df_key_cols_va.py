def manifest_rows(section, df, key_cols, value_col, source_col=None, pairs_col=None, lo=None, hi=None, note_col=None):
    out = []
    for _, r in df.iterrows():
        out.append({"section": section, "key": "|".join(str(r[c]) for c in key_cols),
                    "value": r[value_col], "source": r[source_col] if source_col else "",
                    "pairs": r[pairs_col] if pairs_col else "",
                    "ci_low": r[lo] if lo else "", "ci_high": r[hi] if hi else "",
                    "note": r[note_col] if note_col else ""})
    return out


def _clean_cell(v):
    if v is None:
        return ""
    if isinstance(v, (float, np.floating)):
        if np.isnan(v):
            return ""
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    return v if isinstance(v, (int, float, str)) else str(v)


def _column_values(s):
    """A column as Python values xlsxwriter writes directly: NaN and '' become blanks."""
    a = s.to_numpy()
    if a.dtype.kind in "fc":
        return [None if v != v else float(v) for v in a.tolist()]
    if a.dtype.kind in "iu":
        return a.tolist()
    if a.dtype.kind == "b":
        return a.tolist()
    return [None if (v is None or v == "" or (isinstance(v, float) and v != v)) else
            (v if isinstance(v, (str, int, float, bool)) else str(v)) for v in a.tolist()]


def write_workbook(path, tables, row_limit, filters=None):
    """tables: ordered {sheet name: DataFrame}. Streams rows (xlsxwriter constant_memory).
    Returns {sheet: [sheet names written]}."""
    import xlsxwriter
    wb = xlsxwriter.Workbook(str(path), {"constant_memory": True, "strings_to_urls": False,
                                         "strings_to_formulas": False, "nan_inf_to_errors": True})
    head = wb.add_format({"bold": True, "bg_color": "#DDE3EA"})
    written = {}
    for name, df in tables.items():
        cols = [str(c) for c in df.columns]
        n = len(df)
        parts = max(1, math.ceil(n / row_limit))
        written[name] = []
        cols_py = [_column_values(df[c]) for c in df.columns]
        for k in range(parts):
            sname = name if k == 0 else f"{name} ({k + 1})"
            ws = wb.add_worksheet(sname[:31])
            written[name].append(sname)
            ws.write_row(0, 0, cols, head)
            lo, hi = k * row_limit, min(n, (k + 1) * row_limit)
            for i in range(lo, hi):
                ws.write_row(i - lo + 1, 0, [col[i] for col in cols_py])
            ws.autofilter(0, 0, max(1, hi - lo), max(0, len(cols) - 1))
            ws.freeze_panes(1, 0)
    wb.close()
    return written


def workbook_tables(run, selfcheck, manifest, cfg):
    """The summary workbook's sheets (the full tables go to files)."""
    ent, pairs, ev = run["entities"], run["pairs"], run["evidence"]
    flagged = ent[ent["p"] >= cfg.flag_p].sort_values(["p", "entity_id"], ascending=[False, True], kind="stable")
    cut = flagged.head(cfg.workbook_flagged_max)
    best_ids = []
    if len(pairs):
        ok = pairs[pairs["veto"] == ""]
        key = cut["entity_id"] + "~"
        bw = dict(zip(ent["entity_id"] + "|" + ent["best_watchlist_record_id"], ent["entity_id"]))
        sel = ok[(ok["entity_id"].isin(set(cut["entity_id"]))) &
                 ((ok["entity_id"] + "|" + ok["watchlist_record_id"]).isin(set(bw)))]
        best = sel.drop(columns=["_e", "_r"])
        cards = decision_cards(ev, best["pair_id"])
        best = best.assign(decision_card=best["pair_id"].map(cards).fillna(""))
        best = best.sort_values(["p", "pair_id"], ascending=[False, True], kind="stable")
    else:
        best = pd.DataFrame()
    # samples: per basis x p band
    samples = pd.DataFrame()
    if len(pairs):
        rng = np.random.default_rng(cfg.seed + 5)
        s = pairs.assign(band=p_band(pairs["p"].to_numpy()))
        picks = []
        for (_, _), g in s.groupby(["basis", "band"], sort=True):
            n = min(len(g), cfg.workbook_sample_per_stratum)
            picks.append(g.iloc[np.sort(rng.choice(len(g), n, replace=False))])
        samples = pd.concat(picks, ignore_index=True).drop(columns=["_e", "_r"])
        samples["decision_card"] = samples["pair_id"].map(decision_cards(ev, samples["pair_id"])).fillna("")
    summ = [("dataset", cfg.dataset), ("io_format", cfg.io_format), ("exhaustive", cfg.exhaustive),
            ("address_standardizer", cfg.address_standardizer), ("baseline", cfg.baseline),
            ("extracted parties", int(len(run["rows"]))), ("extracted entities", int(len(ent))),
            ("pooled entities (more than one record)", int((ent["records"] > 1).sum())),
            ("candidate pairs kept", int(len(pairs))),
            (f"entities with best p >= {cfg.flag_p}", int(len(flagged))),
            (f"  of which rest on the name (contextual or name only)", int(flagged["rests_on_name"].sum()) if len(flagged) else 0),
            ("entities with a consistent watchlist cluster", int((ent["match_status"] == "linked in a consistent cluster").sum())),
            ("entities with conflicting candidates", int((ent["conflicting_candidates"] != "").sum()))]
    if selfcheck and len(selfcheck.get("bands", [])):
        for _, r in selfcheck["bands"].iterrows():
            if r["method"] == "baseline" or r["threshold"] in (0.5, 0.9):
                summ.append((f"self-check {r['test']} {r['method']} at {r['threshold']}",
                             f"precision {r['precision']:.4f}, recall {r['recall']:.4f} ({r['tp']} of {r['true_pairs']} true pairs, {r['fp']} false)"))
        for _, r in selfcheck["funnel"].iterrows():
            if r["method"] == "B1":
                summ.append((f"self-check {r['test']}: true pairs lost by the candidate stage",
                             f"{r['lost_at_candidates']} of {r['true_pairs']}"))
    tables = {"summary": pd.DataFrame(summ, columns=["item", "value"]).astype({"value": str}),
              "flagged_entities": cut.drop(columns=["_e"]), "best_matches": best, "samples": samples}
    if selfcheck:
        sc = []
        for k in ("funnel", "bands", "basis", "bins"):
            t = selfcheck.get(k)
            if isinstance(t, pd.DataFrame) and len(t):
                sc.append(t.assign(table=k))
        tables["self_check"] = pd.concat(sc, ignore_index=True) if sc else pd.DataFrame()
        if cfg.baseline:
            tables["baseline_disagreements"] = selfcheck.get("disagreements", pd.DataFrame())
            tables["baseline_ambiguity"] = selfcheck.get("ambiguity", pd.DataFrame())
    tables["weights"] = weights_output(run["models"])
    tables["manifest"] = manifest
    return tables


def weights_output(models):
    return pd.concat([models[k].weights[p] for k in ("link", "dedup") for p in ("person", "business")],
                     ignore_index=True)