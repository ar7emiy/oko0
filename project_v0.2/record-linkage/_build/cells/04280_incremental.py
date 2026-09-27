def _sha1(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def input_row_hashes(df):
    """record_id -> content hash of the input row (every schema column)."""
    cols = [c for c in SCHEMA if c in df]
    joined = df[cols].astype(str).agg("\x1f".join, axis=1)
    return dict(zip(df["record_id"], [_sha1(s) for s in joined]))


# ---- the model, saved and reloaded -------------------------------------------------------------
def model_payload(models):
    def m(M):
        return {"weights": {p: w.to_json(orient="split") for p, w in M.weights.items()},
                "prior": [[k[0], k[1], v] for k, v in M.prior.items()],
                "prior_df": M.prior_df.to_json(orient="split"),
                "passes": M.passes, "u_sample_pairs": M.u_sample_pairs}
    body = {"link": m(models["link"]), "dedup": m(models["dedup"]), "components": models["components"],
            "sources": models["sources"], "em_loose": models["em_loose"]}
    txt = json.dumps(body, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o), sort_keys=True)
    return _sha1(txt), txt


def model_from_payload(txt):
    body = json.loads(txt)
    from io import StringIO

    def m(kind):
        b = body[kind]
        return Model(kind=kind, weights={p: pd.read_json(StringIO(w), orient="split") for p, w in b["weights"].items()},
                     prior={(a, g): v for a, g, v in b["prior"]}, prior_df=pd.read_json(StringIO(b["prior_df"]), orient="split"),
                     passes=b["passes"], u_sample_pairs=b["u_sample_pairs"])
    return {"link": m("link"), "dedup": m("dedup"), "components": body["components"], "sources": body["sources"],
            "em_loose": body["em_loose"], "centre": {}}


# ---- the link cache: scored pairs per entity signature -------------------------------------------
class LinkCache:
    """Scored entity x watchlist pairs keyed by an entity signature. `table`: the saved cache
    (part, signature, model_id, payload) or None."""

    def __init__(self, xdf, model_id, table=None):
        self.rowhash = input_row_hashes(xdf)
        self.model_id = model_id
        self.saved = {}
        if table is not None and len(table):
            t = table[table["model_id"] == model_id]
            self.saved = {(p, s): pl for p, s, pl in zip(t["part"], t["signature"], t["payload"])}
        self.new = {}
        self.sigs = {}
        self.stats = {"reused": 0, "scored": 0}

    def signatures(self, pr, part, ent, tied=None):
        X = pr.X[part]
        names = pr.ctx.stats.names
        rid = X["record_id"].to_numpy(dtype=object)
        idc = []
        for f, cols in VALUE_FIELDS.items():
            nn = names.get(f)
            for c in cols:
                if c in X:
                    v = X[c].to_numpy(dtype=object)
                    cnt = _lookup(nn, v).astype(int) if nn is not None else np.zeros(len(v), int)
                    idc.append(np.where(v != "", c + "=" + v.astype(str) + "#" + cnt.astype(str), ""))
        per = [self.rowhash.get(r, "") + ";" + ";".join(sorted(x for x in parts if x))
               for r, parts in zip(rid, zip(*idc))] if idc else [self.rowhash.get(r, "") for r in rid]
        tie = X["tie_pos"].to_numpy()
        sig = np.empty(len(ent.ids), dtype=object)
        for e in range(len(ent.ids)):
            mem = ent.members(e)
            s = sorted(per[m] for m in mem)
            if tied is not None:
                s += sorted(tied[tie[m]] for m in mem if tie[m] >= 0)
            sig[e] = _sha1(self.model_id + "|" + part + "|" + "|".join(s))
        self.sigs[part] = sig
        return sig

    def split(self, part):
        sig = self.sigs[part]
        hit = np.array([(part, s) in self.saved for s in sig], dtype=bool)
        return np.flatnonzero(hit), np.flatnonzero(~hit)

    def rebuild(self, pr, part, idx):
        """Cached S, L and summary rows of entities idx, with today's positions."""
        from io import StringIO
        X = pr.X[part]
        pos = pd.Series(np.arange(len(X)), index=X["party_id"].to_numpy())
        S_, L_, E_ = [], [], []
        for e in idx:
            b = json.loads(self.saved[(part, self.sigs[part][e])])
            s = pd.read_json(StringIO(b["S"]), orient="split", dtype=False)
            l = pd.read_json(StringIO(b["L"]), orient="split", dtype=False)
            if len(s):
                s["e"] = e
                for c in [c for c in l.columns if c.startswith("src_")]:
                    l[c] = [int(pos.get(v, -1)) if v else -1 for v in l[c]]
                S_.append(s); L_.append(l)
            E_.append(pd.DataFrame({"candidates": [b["candidates"]], "vetoed": [b["vetoed"]]}, index=[e]))
        self.stats["reused"] += len(idx)
        cat = lambda xs: pd.concat(xs, ignore_index=True) if xs else pd.DataFrame()
        return cat(S_), cat(L_), (pd.concat(E_) if E_ else pd.DataFrame(columns=["candidates", "vetoed"]))

    def remember(self, pr, part, S, L, Es):
        """Store the scored rows of every entity of this run (new and reused) for the next run."""
        X = pr.X[part]
        pid = X["party_id"].to_numpy(dtype=object)
        sig = self.sigs[part]
        groups = pd.Series(np.arange(len(S))).groupby(S["e"].to_numpy()).agg(list) if len(S) else pd.Series(dtype=object)
        for e in range(len(sig)):
            rows = groups.get(e, [])
            s = S.iloc[rows].drop(columns=["e"]) if len(rows) else S.iloc[:0].drop(columns=["e"], errors="ignore")
            l = L.iloc[rows].copy() if len(rows) else L.iloc[:0].copy()
            for c in [c for c in l.columns if c.startswith("src_")]:
                l[c] = [pid[v] if v >= 0 else "" for v in l[c].to_numpy()]
            cand = int(Es["candidates"].get(e, 0)) if len(Es) else 0
            vet = int(Es["vetoed"].get(e, 0)) if len(Es) else 0
            self.new[(part, sig[e])] = json.dumps({"S": s.to_json(orient="split"), "L": l.to_json(orient="split"),
                                                   "candidates": cand, "vetoed": vet})

    def table(self):
        return pd.DataFrame([{"part": p, "signature": s, "model_id": self.model_id, "payload": pl}
                             for (p, s), pl in self.new.items()])


def _coerce_scored(df):
    """One dtype per column of scored rows, whether freshly scored or read back from JSON."""
    d = df.copy()
    for c in d.columns:
        if c in ("e", "r") or c.startswith("src_"):
            d[c] = pd.to_numeric(d[c]).astype(np.int64)
        elif c in FIELD_LEVELS:
            d[c] = pd.to_numeric(d[c]).astype(np.int8)
        elif c.startswith("veto_"):
            d[c] = d[c].astype(bool)
        elif c in ("rank", "p", "bits", "logit", "prior_logit") or c.startswith(("bits_", "uv_", "k_")):
            d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
        elif c in ("rules", "veto", "basis"):
            d[c] = d[c].fillna("").astype(object)
    return d


def score_link_cached(pr, part, ent, model, cfg, cache, tied=None, anchors=None, log=print):
    """score_link_part for the entities whose signature is new; the others from the cache."""
    cache.signatures(pr, part, ent, tied)
    hit, miss = cache.split(part)
    S1, L1, E1, D = score_link_part(pr, part, ent, model, cfg, anchors=anchors, log=log, only_entities=miss)
    S0, L0, E0 = cache.rebuild(pr, part, hit)
    S0, L0 = _coerce_scored(S0), _coerce_scored(L0)
    S1, L1 = _coerce_scored(S1), _coerce_scored(L1)
    cache.stats["scored"] += len(miss)
    if len(S0):
        S = pd.concat([S1, S0], ignore_index=True)
        L = pd.concat([L1, L0], ignore_index=True)
    else:
        S, L = S1, L1
    if len(S):
        order = np.lexsort((S["r"].to_numpy(), S["e"].to_numpy()))
        S, L = S.iloc[order].reset_index(drop=True), L.iloc[order].reset_index(drop=True)
        S["e"] = S["e"].astype(np.int64); S["r"] = S["r"].astype(np.int64)
    Es = pd.concat([E1, E0]).sort_index() if len(E0) else E1
    D["cache"] = {"reused_entities": len(hit), "scored_entities": len(miss)}
    cache.remember(pr, part, S, L, Es)
    log(f"  link {part}: {len(miss):,} entities scored, {len(hit):,} reused from the cache")
    return S, L, Es, D


# ---- state -------------------------------------------------------------------------------------
def read_state(io_):
    t = io_.out_name("run_state")
    if not io_.backend.exists(t):
        return None
    s = io_.backend.read(t)
    return s.iloc[-1].to_dict() if len(s) else None


def write_run_state(io_, run, input_meta):
    """Append this run's state; save the model and the link cache (Delta runs)."""
    mid, txt = model_payload(run["models"])
    b = io_.backend
    tm = io_.out_name("model")
    if not b.exists(tm) or b.read(tm)["model_id"].iloc[-1] != mid:
        b.write(tm, pd.DataFrame([{"model_id": mid, "payload": txt, "run_id": io_.run_id}]), mode="overwrite")
    cache = run.get("link_cache")
    if cache is None:
        cache = LinkCache(run["xdf"], mid)
        eb = run["scored"]["entities"]["business"]
        for part in ("business", "person"):
            ent = run["scored"]["entities"][part]
            tsig = cache.sigs["business"][eb.e_of] if part == "person" and len(eb.e_of) else (
                np.array([], dtype=object) if part == "person" else None)
            cache.signatures(run["pr"], part, ent, tsig)
            S, L, Es, _ = run["scored"]["link"][part]
            cache.remember(run["pr"], part, S, L, Es)
    ct = cache.table()
    if len(ct):
        ct["_row_hash"] = [_sha1(p) for p in ct["payload"]]
        b.merge(io_.out_name("link_cache"), ct, ["part", "signature"], delete_missing=True)
    st = {"run_id": io_.run_id, "model_id": mid, "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
          "extracted_table": input_meta.get("extracted.table", ""), "extracted_version": input_meta.get("extracted.version", -1),
          "watchlist_table": input_meta.get("watchlist.table", ""), "watchlist_version": input_meta.get("watchlist.version", -1),
          "mode": run.get("incremental", {}).get("mode", "full")}
    b.write(io_.out_name("run_state"), pd.DataFrame([st]), mode="append")
    return st


def changed_records(io_, table, since, until):
    """record_ids inserted/updated and deleted in (since, until]: the change data feed, or a
    comparison of the two versions when the feed is unavailable."""
    b = io_.backend
    try:
        ch = b.changes(table, since + 1, until)
        ch = ch[ch["_change_type"] != "update_preimage"]
        upd = set(ch.loc[ch["_change_type"].isin(["insert", "update_postimage"]), "record_id"].astype(str))
        dele = set(ch.loc[ch["_change_type"] == "delete", "record_id"].astype(str)) - upd
        return upd, dele, "change data feed"
    except Exception:
        old = b.read(table, since)
        new = b.read(table, until)
        ho, hn = input_row_hashes(old.astype(str)), input_row_hashes(new.astype(str))
        upd = {r for r, h in hn.items() if ho.get(r) != h}
        return upd, set(ho) - set(hn), "version diff"


def run_incremental(xdf, wdf, maps, ref, cfg, io_, log=print, sw=None, truth_file=None):
    """The incremental run (section 15b): a full run when there is no usable state."""
    mark = sw.mark if sw is not None else (lambda s: None)
    state = read_state(io_)
    info = io_.info
    reason = ""
    tm = io_.out_name("model")
    if cfg.delta_full_refresh:
        reason = "delta_full_refresh"
    elif state is None:
        reason = "no saved state"
    elif not io_.backend.exists(tm):
        reason = "no saved model"
    elif int(state["watchlist_version"]) != int(info.get("watchlist.version", -1)):
        reason = "the watchlist changed"
    if reason:
        log(f"incremental: full run ({reason})")
        run = run_pipeline(xdf, wdf, maps, ref, cfg, truth_file, log=log, sw=sw)
        run["xdf"] = xdf
        run["incremental"] = {"mode": "full", "reason": reason}
        return run
    since, until = int(state["extracted_version"]), int(info["extracted.version"])
    upd, dele, how = changed_records(io_, info["extracted.table"], since, until)
    log(f"incremental: extracted versions {since} -> {until}: {len(upd)} rows new or changed, {len(dele)} deleted ({how})")
    mrow = io_.backend.read(tm).iloc[-1]
    models = model_from_payload(mrow["payload"])
    ct = io_.out_name("link_cache")
    cache = LinkCache(xdf, mrow["model_id"], io_.backend.read(ct) if io_.backend.exists(ct) else None)
    pr = prepare(xdf, wdf, maps, ref, cfg, log=log)
    pr.ctx.components = models["components"].get("link", {})
    pr.ctx_dedup.components = models["components"].get("dedup", {})
    mark("2-6 normalize ... (incremental)")
    scored = score_all(pr, models, cfg, log=log, cache=cache)
    mark("7, 12 deduplication, linking of changed entities, clusters")
    out = assemble_outputs(pr, models, scored, xdf, cfg, truth_file, log)
    out.update({"pr": pr, "models": models, "scored": scored, "xdf": xdf, "link_cache": cache,
                "params": {"weights": models["link"].weights, "components": models["components"].get("link"),
                           "sources": models["sources"], "em": models["em_loose"]},
                "prior_df": models["link"].prior_df,
                "incremental": {"mode": "incremental", "since_version": since, "until_version": until,
                                "changed_rows": len(upd), "deleted_rows": len(dele), "detected_by": how,
                                **{f"{k}_entities": v for k, v in cache.stats.items()}}})
    info.update({f"incremental.{k}": v for k, v in out["incremental"].items()})
    mark("13-16 roll-ups (incremental)")
    return out
