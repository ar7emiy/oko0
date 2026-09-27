"""One-time edit of the self-test cell for B1 (entity grain, level names, signatures)."""
from pathlib import Path

p = Path(__file__).resolve().parent / "cells" / "06600_import_unittest_tempfile_io.py"
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        raise SystemExit(f"expected {count} of {old[:70]!r}, found {n}")
    s = s.replace(old, new)


rep('cfg = make_config("selftest", random_pairs=150_000, sim_records=4_000, chunk_size=700)',
    'cfg = make_config("selftest", random_pairs=150_000, dedup_random_pairs=150_000, sim_records=4_000,\n'
    '                          chunk_size=700, bootstrap_reps=40, io_format="csv", exhaustive=False, baseline=False,\n'
    '                          address_standardizer="usaddress", self_check=False, incremental=False)')
rep('''                          {"first_nick_or_close": 0.01, "first_initial": 0.05, "first_empty": 0.05,
                           "first_differs": 0.9, "last_close": 0.002})''',
    '''                          {"first_nick": 0.005, "first_close": 0.005, "first_agrees_fuzzy": 0.01, "first_initial": 0.05,
                           "first_empty": 0.05, "first_differs": 0.9, "last_close": 0.002, "last_sound": 0.004})''')
rep('''(("Bill", "Szczepanski"), ("William", "Szczepanski"), "first_nick_or_close"),''',
    '''(("Bill", "Szczepanski"), ("William", "Szczepanski"), "first_nick"),
                 (("Jonathon", "Kowalczyk"), ("Jonathan", "Kowalczyk"), "first_close"),
                 (("Maria", "Smyth"), ("Maria", "Smith"), "last_sound_first_agrees"),''')
# candidates: entity grain
rep('''    def test_cross_file_same_part_only(self):
        S = _small_run()["scored"]
        for part in ("person", "business"):
            s = S[part][0]
            self.assertTrue((s["l"] < len(self.pr.X[part])).all() and (s["r"] < len(self.pr.W[part])).all())''',
    '''    def test_cross_file_same_part_only(self):
        S = _small_run()["scored"]
        for part in ("person", "business"):
            s = S["link"][part][0]
            ents = S["entities"][part]
            self.assertTrue((s["e"] < len(ents.ids)).all() and (s["r"] < len(self.pr.W[part])).all())''')
rep('''            l, r = strict_pairs(X, W, part, self.pr.ctx)
            keys = self.pr and _small_run()["scored"][part][3]["keys"]
            k = l.astype(np.int64) * np.int64(1 << 32) + r''',
    '''            l, r = strict_pairs(X, W, part, self.pr.ctx)
            sc = _small_run()["scored"]
            keys = sc["link"][part][3]["keys"]
            k = _key(sc["entities"][part].e_of[l], r)''')
rep('S, L = self.run["scored"][part][0], self.run["scored"][part][1]',
    'S, L = self.run["scored"]["link"][part][0], self.run["scored"]["link"][part][1]', count=3)
rep('''        S, L = self.run["scored"]["person"][0], self.run["scored"]["person"][1]
        cp = S["bits_co_party"].to_numpy() > 0
        self.assertTrue((S["bits_name"].to_numpy()[cp] > 0).all())
        self.assertTrue((L["co_party"].to_numpy()[cp] == 0).all())
        anchors = business_anchors(self.run["scored"]["business"][0], _env()[0])
        X, W = self.run["pr"].X["person"], self.run["pr"].W["person"]
        tl, tr = X["tie_pos"].to_numpy()[S["l"].to_numpy()[cp]], W["tie_pos"].to_numpy()[S["r"].to_numpy()[cp]]
        self.assertTrue(np.isin(tl.astype(np.int64) * np.int64(1 << 32) + tr, anchors).all())''',
    '''        sc = self.run["scored"]
        S, L = sc["link"]["person"][0], sc["link"]["person"][1]
        cp = S["bits_co_party"].to_numpy() > 0
        self.assertGreater(int(cp.sum()), 0)
        self.assertTrue((S["bits_name"].to_numpy()[cp] > 0).all())
        self.assertTrue((L["co_party"].to_numpy()[cp] == 0).all())
        anchors = link_anchors(sc["link"]["business"][0], sc["entities"]["business"], _env()[0])
        X, W = self.run["pr"].X["person"], self.run["pr"].W["person"]
        ep = sc["entities"]["person"]
        for e, r in zip(S["e"].to_numpy()[cp], S["r"].to_numpy()[cp]):
            tl = X["tie_pos"].to_numpy()[ep.members(e)]
            tl = tl[tl >= 0]
            tr = W["tie_pos"].to_numpy()[r]
            ks = _key(anchors["e_of_business"][tl], np.full(len(tl), tr))
            self.assertTrue(np.isin(ks, anchors["keys"]).any())''')
rep('''        a = self.run["pairs"].drop(columns=["_l", "_r"]).reset_index(drop=True)
        b = again["pairs"].drop(columns=["_l", "_r"]).reset_index(drop=True)''',
    '''        a = self.run["pairs"].drop(columns=["_e", "_r"]).reset_index(drop=True)
        b = again["pairs"].drop(columns=["_e", "_r"]).reset_index(drop=True)''')
rep('''        r = check_edge_cases(self.run["pr"], self.run["pairs"], None, self.run["scored"], self.run["entities"], edges)''',
    '''        r = check_edge_cases(self.run["pr"], self.run["pairs"], self.run["rows"], self.run["scored"], edges)''')
rep('''    def test_entities_one_row_per_party(self):
        e = self.run["entities"]
        self.assertTrue(e["party_id"].is_unique)
        n = sum(len(self.run["pr"].X[p]) for p in ("person", "business"))
        self.assertEqual(len(e), n)''',
    '''    def test_rows_one_per_party_entities_one_per_entity(self):
        # B1: the grain changed. Rows: one per extracted party (as the v1.0 entities sheet was);
        # entities: one per pooled entity; every row points to its entity's result.
        rows, e = self.run["rows"], self.run["entities"]
        self.assertTrue(rows["party_id"].is_unique)
        n = sum(len(self.run["pr"].X[p]) for p in ("person", "business"))
        self.assertEqual(len(rows), n)
        self.assertTrue(e["entity_id"].is_unique)
        self.assertTrue(rows["entity_id"].isin(set(e["entity_id"])).all())
        self.assertEqual(int(e["records"].sum()), n)
        m = rows.merge(e[["entity_id", "p"]], on="entity_id", suffixes=("", "_e"))
        self.assertTrue(np.allclose(m["p"], m["p_e"]))''')
rep('''        m = build_manifest(cfg, {"x": "0"}, ref, ({"source": "x", "rows": 1, "all_empty_columns": [], "added_columns": [],
                                                   "passthrough_columns": []},), run["pr"], run["params"],
                           run["prior_df"], sensitivity(pd.DataFrame({"part": [], "prior_group": [], "bits": []}),
                                                        run["prior_df"], cfg), run["scored"], run["diag"], sw)
        for s in ("config", "config.core", "reference", "m", "u", "prior", "blocking", "data_quality", "timing"):''',
    '''        m = build_manifest(cfg, {"x": "0"}, ref, ({"source": "x", "rows": 1, "all_empty_columns": [], "added_columns": [],
                                                   "passthrough_columns": []},), run["pr"], run["models"],
                           run["sens"], run["scored"], run["diag"], sw, None, {"run_id": "r1"})
        for s in ("config", "config.core", "run", "reference", "m", "u", "bits", "prior", "blocking", "dedup",
                  "m.em_passes", "u.sample", "data_quality", "timing"):''')
p.write_text(s, encoding="utf-8", newline="\n")
print("ok")
