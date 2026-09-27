PERSON_RULES = ["ssn", "npi", "dl", "license", "email", "vin", "plate", "phone", "near_ids",
                "nysiis_initial", "nysiis_canon_initial", "nysiis_first_missing", "nysiis_last",
                "last_part_initial", "first_sound_last_initial", "dob_initial", "dob", "swapped",
                "sn_last_first", "sn_first_last", "street"]
BUSINESS_RULES = ["tin", "cnpi", "email", "phone", "near_ids", "rare_word", "rare_word_sound",
                  "lead_word_state", "sn_sorted_name", "street"]
IDENTIFIER_RULES = {"ssn", "npi", "dl", "license", "email", "vin", "plate", "phone", "tin", "cnpi", "near_ids"}
SN_RULES = {"sn_last_first", "sn_first_last", "sn_sorted_name"}
ASYMMETRIC_RULES = {"swapped", "nysiis_first_missing"}     # x-side and w-side keys differ
NEAR_ID_TYPES = {"person": ["ssn", "npi", "dl", "phone"], "business": ["tin", "phone"]}


def _deletion_keys(v):
    """Every string with one character deleted: two values one substitution or one adjacent
    transposition apart share at least one of these keys."""
    return {v[:i] + v[i + 1:] for i in range(len(v))}


def rule_keys(parties, part, rule, rarity, side="x", dba_pairs=None):
    """Long frame (pos, key, state) of one rule's keys; a party can have several keys."""
    p = parties
    pos = np.arange(len(p))
    st = p["state"].to_numpy(dtype=object)
    if rule in ("ssn", "npi", "dl", "license", "email", "vin", "plate", "tin", "cnpi"):
        k = p[f"id_{rule}"].to_numpy(dtype=object)
        if rule in ("dl", "license", "plate"):                   # number only: states may be unstated
            k = np.array([v.partition(":")[2] if v else "" for v in k], dtype=object)
        return _frame(pos, k, st)
    if rule == "phone":
        if part == "person":
            return pd.concat([_frame(pos, p["phone_own"].to_numpy(dtype=object), st),
                              _frame(pos, p["phone_row"].to_numpy(dtype=object), st)], ignore_index=True)
        return _frame(pos, p["phone_row"].to_numpy(dtype=object), st)
    if rule == "near_ids":
        # B1: one digit mistyped or two transposed in SSN, NPI, DL, TIN or a phone
        rows_p, rows_k = [], []
        for t in NEAR_ID_TYPES[part]:
            cols = ["phone_own", "phone_row"] if t == "phone" else [f"id_{t}"]
            for c in cols:
                if c not in p:
                    continue
                for i, v in enumerate(p[c].to_numpy(dtype=object)):
                    if not v:
                        continue
                    v = v.partition(":")[2] if t == "dl" else v
                    for key in _deletion_keys(v):
                        rows_p.append(i); rows_k.append(f"{t}:{key}")
        rp = np.array(rows_p, dtype=np.int64)
        return _frame(rp, np.array(rows_k, dtype=object), st[rp] if len(rp) else np.array([], dtype=object))
    if rule == "street":
        return _frame(pos, p["addr_street"].to_numpy(dtype=object), st)
    first = p["first"].to_numpy(dtype=object)
    last = p["last"].to_numpy(dtype=object)
    ny = p["last_nysiis"].to_numpy(dtype=object)
    ini = np.array([f[:1] for f in first], dtype=object)
    if rule == "nysiis_initial":
        k = np.where((ny != "") & (ini != ""), ny + "|" + ini, "")
        return _frame(pos, k, st)
    if rule == "nysiis_canon_initial":
        rows_p, rows_k = [], []
        for i, (n, f, roots) in enumerate(zip(ny, first, p["first_roots"].to_numpy(dtype=object))):
            if not n or not f:
                continue
            for letter in sorted({r[:1] for r in roots.split("|") if r}):
                rows_p.append(i); rows_k.append(f"{n}|{letter}")
        return _frame(np.array(rows_p, dtype=np.int64), np.array(rows_k, dtype=object), st[rows_p] if rows_p else np.array([], dtype=object))
    if rule == "nysiis_first_missing":
        # added by the build: a surname with no first name meets every holder of the surname
        k = np.where((ny != "") & ((ini == "") if side == "x" else True), ny, "")
        return _frame(pos, k, st)
    if rule == "nysiis_last":
        # B1: the surname's sound alone (any first name: an unknown nickname, a changed first name)
        return _frame(pos, ny, st)
    if rule == "last_part_initial":
        # B1: each part of a compound surname (GARCIA-VILLANUEVA meets GARCIA) + first initial
        rows_p, rows_k = [], []
        for i, (l_, f) in enumerate(zip(last, first)):
            if not l_ or not f:
                continue
            for w_ in {x for x in re.split(r"[ \-]", l_) if len(x) > 1}:
                rows_p.append(i); rows_k.append(f"{_nysiis_c(w_)}|{f[0]}")
        rp = np.array(rows_p, dtype=np.int64)
        return _frame(rp, np.array(rows_k, dtype=object), st[rp] if len(rp) else np.array([], dtype=object))
    if rule == "first_sound_last_initial":
        # B1: a changed or badly mistyped surname: the first name's sound + the surname's initial
        k = np.array([f"{_nysiis_c(f)}|{l_[0]}" if (len(f) > 1 and l_) else "" for f, l_ in zip(first, last)],
                     dtype=object)
        return _frame(pos, k, st)
    if rule == "dob_initial":
        dob = p["dob"].to_numpy(dtype=object)
        k = np.where((dob != "") & (ini != ""), dob + "|" + ini, "")
        return _frame(pos, k, st)
    if rule == "dob":
        # B1: the date of birth alone (a changed surname and a changed first name)
        return _frame(pos, p["dob"].to_numpy(dtype=object), st)
    if rule == "swapped":
        k = np.where((first != "") & (last != ""), (first + "|" + last) if side == "x" else (last + "|" + first), "")
        return _frame(pos, k, st)
    if rule == "sn_last_first":
        k = np.where(last != "", last + " " + first, "")
        return _frame(pos, k, st)
    if rule == "sn_first_last":
        # B1: sorted on "first last", so a surname typo early in the name still meets its match
        k = np.where((last != "") & (first != ""), first + " " + last, "")
        return _frame(pos, k, st)
    al = p["org_aliases"].to_numpy(dtype=object)
    if rule in ("rare_word", "rare_word_sound"):
        # the two rarest words of each alias (B1: two, not one), and of every alias another
        # record declares as its d/b/a partner (so a trade name meets the legal name);
        # rare_word_sound: their NYSIIS codes (a typo in the rare word)
        partners = defaultdict(set)
        for q1, q2 in (dba_pairs or []):
            a1, a2 = " ".join(sorted(q1)), " ".join(sorted(q2))
            partners[a1].add(q2); partners[a2].add(q1)
        rows_p, rows_k = [], []
        for i, s in enumerate(al):
            for a in (s.split("|") if s else []):
                ws = a.split()
                sets = [ws] + [sorted(q) for q in partners.get(" ".join(sorted(ws)), ())]
                for w_ in sets:
                    if w_:
                        for t in sorted(set(w_), key=lambda t: (-rarity.org_idf(t), t))[:2]:
                            rows_p.append(i)
                            rows_k.append(t if rule == "rare_word" else (_nysiis_c(t) if len(t) >= 4 else ""))
        rp = np.array(rows_p, dtype=np.int64)
        return _frame(rp, np.array(rows_k, dtype=object), st[rp] if len(rp) else np.array([], dtype=object))
    if rule == "lead_word_state":
        k = np.array([(s.split("|")[0].split()[0] + "|" + t) if s and t else "" for s, t in zip(al, st)], dtype=object)
        return _frame(pos, k, st)
    if rule == "sn_sorted_name":
        k = np.array([" ".join(sorted(s.split("|")[0].split())) if s else "" for s in al], dtype=object)
        return _frame(pos, k, st)
    raise ValueError(rule)


def _frame(pos, key, state):
    f = pd.DataFrame({"pos": np.asarray(pos, dtype=np.int64), "key": np.asarray(key, dtype=object),
                      "state": np.asarray(state, dtype=object)})
    return f[f["key"] != ""].drop_duplicates(["pos", "key"]).reset_index(drop=True)


def plan_rule(xk, wk, rule, cap):
    """Effective keys after refining oversized keys by state. Returns (xk, wk, report rows)."""
    cx = xk["key"].value_counts()
    cw = wk["key"].value_counts()
    both = cx.index.intersection(cw.index)
    prod = cx[both] * cw[both]
    total = int(prod.sum())
    big = set(prod.index[prod > cap]) if rule not in SN_RULES else set()
    rep = {"rule": rule, "pairs_before_refine": total, "oversized_keys": len(big),
           "dropped_keys": 0, "dropped_pairs": 0, "pairs_after_refine": total, "dropped_examples": ""}
    if big:
        def refine(f):
            f = f.copy()
            m = f["key"].isin(big)
            f.loc[m, "key"] = np.where(f.loc[m, "state"] != "", f.loc[m, "key"] + "|" + f.loc[m, "state"], "")
            return f[f["key"] != ""]
        xk, wk = refine(xk), refine(wk)
        cx2, cw2 = xk["key"].value_counts(), wk["key"].value_counts()
        b2 = cx2.index.intersection(cw2.index)
        prod2 = cx2[b2] * cw2[b2]
        drop = prod2[prod2 > cap]
        if len(drop):
            xk = xk[~xk["key"].isin(drop.index)]
            wk = wk[~wk["key"].isin(drop.index)]
        rep.update(dropped_keys=int(len(drop)), dropped_pairs=int(drop.sum()),
                   pairs_after_refine=int(prod2.sum() - drop.sum()),
                   dropped_examples="; ".join(f"{k} ({v:,})" for k, v in drop.sort_values(ascending=False).head(5).items()))
    elif rule in SN_RULES:
        # exact-duplicate keys over the cap stay with the refined blocks
        over = set(prod.index[prod > cap])
        if over:
            xk = xk[~xk["key"].isin(over)]
            wk = wk[~wk["key"].isin(over)]
            rep.update(dropped_keys=len(over), dropped_pairs=int(prod[list(over)].sum()),
                       dropped_examples="left to the name blocks: " + "; ".join(sorted(over)[:5]))
    return xk.reset_index(drop=True), wk.reset_index(drop=True), rep


class CandidatePlan:
    """Keys of every rule for one part, prepared once for all chunks. `same_frame`: the
    extracted file against itself (deduplication): each unordered pair once (l < r).
    `exhaustive`: every same-type pair is a candidate; the rules still say which of them
    would also have proposed it."""

    def __init__(self, xp, wp, part, rarity, cfg, dba_pairs=None, same_frame=False, exhaustive=None):
        self.part, self.cfg, self.same = part, cfg, same_frame
        self.exhaustive = cfg.exhaustive if exhaustive is None else exhaustive
        self.rules = list(PERSON_RULES if part == "person" else BUSINESS_RULES)
        if self.exhaustive:
            self.rules.append("exhaustive")
        self.bit = {r: 1 << i for i, r in enumerate(self.rules)}
        self.keys, self.report = {}, []
        for r in self.rules:
            if r == "exhaustive":
                continue
            xk, wk, rep = plan_rule(rule_keys(xp, part, r, rarity, dba_pairs=dba_pairs),
                                    rule_keys(wp, part, r, rarity, side="w", dba_pairs=dba_pairs), r,
                                    cfg.block_pair_cap)
            rep["part"] = part
            self.report.append(rep)
            sk = None
            if r in SN_RULES:
                sk = np.sort(pd.unique(np.concatenate([xk["key"].to_numpy(dtype=object),
                                                       wk["key"].to_numpy(dtype=object)])).astype(str))
            self.keys[r] = (xk, wk, sk)
        self.n_x, self.n_w = len(xp), len(wp)

    def _join(self, r, xk, wk, sk, pos):
        """Pairs (x-side pos in `pos`, w-side pos) proposed by rule r."""
        xc = xk[np.isin(xk["pos"].to_numpy(), pos)]
        if not len(xc) or not len(wk):
            return None
        xf = pd.DataFrame({"key": xc["key"].to_numpy(dtype=object)})
        wf = pd.DataFrame({"key": wk["key"].to_numpy(dtype=object)})
        idx = rl.Index()
        if r in SN_RULES:
            idx.add(rl.index.SortedNeighbourhood("key", "key", window=self.cfg.sn_window, sorting_key_values=sk))
        else:
            idx.add(rl.index.Block("key", "key"))
        mi = idx.index(xf, wf)
        if len(mi) == 0:
            return None
        return (xc["pos"].to_numpy()[mi.get_level_values(0).to_numpy()],
                wk["pos"].to_numpy()[mi.get_level_values(1).to_numpy()])

    def chunk_positions(self, pos):
        """Candidate pairs whose extracted party is in `pos`: (l, r, rules bit mask)."""
        pos = np.unique(np.asarray(pos, dtype=np.int64))
        ls, rs, bs = [], [], []
        for r in self.rules:
            if r == "exhaustive":
                continue
            xk, wk, sk = self.keys[r]
            got = self._join(r, xk, wk, sk, pos)
            if got is not None:
                ls.append(got[0]); rs.append(got[1]); bs.append(np.full(len(got[0]), self.bit[r], dtype=np.int64))
            if self.same and r in ASYMMETRIC_RULES:
                # the other direction, so each unordered pair is found from its smaller member
                got = self._join(r, wk, xk, sk, pos)
                if got is not None:
                    ls.append(got[0]); rs.append(got[1]); bs.append(np.full(len(got[0]), self.bit[r], dtype=np.int64))
        if self.exhaustive and len(pos):
            n_r = self.n_w
            ls.append(np.repeat(pos, n_r)); rs.append(np.tile(np.arange(n_r, dtype=np.int64), len(pos)))
            bs.append(np.full(len(pos) * n_r, self.bit["exhaustive"], dtype=np.int64))
        if not ls:
            return pd.DataFrame({"l": np.array([], np.int64), "r": np.array([], np.int64),
                                 "rules": np.array([], np.int64)})
        l = np.concatenate(ls); r_ = np.concatenate(rs); b = np.concatenate(bs)
        if self.same:
            keep = l < r_
            l, r_, b = l[keep], r_[keep], b[keep]
        key = l * np.int64(1 << 32) + r_
        order = np.argsort(key, kind="stable")
        key, b = key[order], b[order]
        if not len(key):
            return pd.DataFrame({"l": np.array([], np.int64), "r": np.array([], np.int64),
                                 "rules": np.array([], np.int64)})
        starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        bits = np.bitwise_or.reduceat(b, starts)
        uk = key[starts]
        return pd.DataFrame({"l": uk >> 32, "r": uk & np.int64((1 << 32) - 1), "rules": bits})

    def chunk(self, lo, hi):
        """Candidate pairs for extracted parties with positions in [lo, hi)."""
        return self.chunk_positions(np.arange(lo, hi, dtype=np.int64))

    def chunks(self, n_parties=None):
        """Position chunks covering the extracted side: chunk_size parties (blocking), or as
        many as keep a chunk near exhaustive_pairs_per_chunk pairs (exhaustive)."""
        n = self.n_x if n_parties is None else n_parties
        step = self.cfg.chunk_size
        if self.exhaustive:
            step = max(1, min(step, self.cfg.exhaustive_pairs_per_chunk // max(1, self.n_w)))
        return [(lo, min(n, lo + step)) for lo in range(0, n, step)]

    def rule_names(self, bits):
        return [",".join(r for r in self.rules if b & self.bit[r]) for b in bits]
