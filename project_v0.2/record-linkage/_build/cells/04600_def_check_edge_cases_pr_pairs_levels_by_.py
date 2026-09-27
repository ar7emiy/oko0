def check_edge_cases(pr, pairs, rows, scored, edges):
    """One row per expectation: ok / failed with the reason. An extracted record is judged
    through the entity it was pooled into."""
    out = []
    empty = set(pr.reports["empty_rows_extracted"]["record_id"])
    ent_of = rows.set_index(["record_id", "part"])["entity_id"] if len(rows) else pd.Series(dtype=object)
    for c in edges:
        for ex in c["expect"]:
            problems = []
            if ex.get("empty_row"):
                if ex["x"] not in empty:
                    problems.append("not reported as an empty row")
                out.append({"case": c["case"], "desc": c["desc"], "x": ex["x"], "part": ex["part"], "w": "",
                            "ok": not problems, "problems": "; ".join(problems)})
                continue
            part = ex["part"]
            X = pr.X[part]
            xi = X.index[X["record_id"] == ex["x"]]
            if ex.get("party"):
                if not len(xi):
                    problems.append("party missing")
                else:
                    e = X.loc[xi[0]]
                    for k, v in ex["party"].items():
                        got = e[k]
                        if bool(got == v) is False:
                            problems.append(f"{k}={got!r}, expected {v!r}")
            if ex.get("w"):
                eid = ent_of.get((ex["x"], part), None)
                P = pairs[(pairs["part"] == part) & (pairs["entity_id"] == eid) &
                          (pairs["watchlist_record_id"] == ex["w"])] if eid is not None else pairs.iloc[:0]
                if not len(P):
                    if not ex.get("if_visible"):      # a strong negative may fall below the keep rule
                        problems.append("pair not visible")
                else:
                    pr_ = P.iloc[0]
                    if "basis" in ex and pr_["basis"] != ex["basis"]:
                        problems.append(f"basis {pr_['basis']}, expected {ex['basis']}")
                    if "basis_not" in ex and pr_["basis"] == ex["basis_not"]:
                        problems.append(f"basis must not be {ex['basis_not']}")
                    if "veto" in ex and pr_["veto"] != ex["veto"]:
                        problems.append(f"veto {pr_['veto']!r}, expected {ex['veto']!r}")
                    if ex.get("veto") and pr_["p"] != 0:
                        problems.append("vetoed pair must have p = 0")
                    if ex.get("rank") and pr_["rank"] != ex["rank"]:
                        problems.append(f"rank {pr_['rank']}, expected {ex['rank']}")
                    if ex.get("levels"):
                        S, L = scored["link"][part][0], scored["link"][part][1]
                        m = (S["e"].to_numpy() == pr_["_e"]) & (S["r"].to_numpy() == pr_["_r"])
                        lv = L[m].iloc[0]
                        for f, want in ex["levels"].items():
                            code = int(lv[f]) if f in lv else EMPTY
                            got = "empty" if code < 0 else FIELD_LEVELS[f][code]
                            if got != want:
                                problems.append(f"{f} level {got}, expected {want}")
            out.append({"case": c["case"], "desc": c["desc"], "x": ex["x"], "part": part, "w": ex.get("w", ""),
                        "ok": not problems, "problems": "; ".join(problems)})
    return pd.DataFrame(out)
