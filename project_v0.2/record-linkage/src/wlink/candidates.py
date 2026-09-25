# %% [markdown]
# ## 7 · Candidates
#
# Only extracted × watchlist pairs of the same part type are ever proposed. The union of these
# rules, each pair remembering which rules proposed it:
#
# | Part | Rules |
# |---|---|
# | Person | exact SSN, provider NPI, DL (state:number), licence (state:number), email, VIN, plate; any phone; NYSIIS(last) + first initial; NYSIIS(last) + canonical first initial (Bill meets William); exact DOB + first initial (a surname change); swapped first/last; sorted neighbourhood on "last first" (window 5) |
# | Business | exact TIN, clinic NPI, email, work phone; rarest word of each alias (d/b/a included); leading word + state; sorted neighbourhood on the sorted-word name |
#
# **Before indexing**, every rule's pair count is computed from key counts on both sides and
# printed. A key that would propose more than `block_pair_cap` pairs is refined with the state;
# a refined key still over the cap is dropped and listed in the manifest with its pair count
# (an unresolved outcome, never a silent loss). Keys shared by more than the cap in the sorted
# neighbourhood are left to the refined blocks. Indexing runs in chunks of `chunk_size`
# extracted parties through `recordlinkage.Index` (`Block`, `SortedNeighbourhood` with the
# global sorting-key values, so a chunked run proposes exactly the pairs of an unchunked one).
#
# **Where Splink would do better.** Splink's blocking runs as SQL joins in DuckDB, parallel
# and out of core, and its `cumulative_comparisons_to_be_scored_from_blocking_rules_chart`
# shows each rule's marginal pairs. recordlinkage's `Block` is a pandas merge per chunk.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *

PERSON_RULES = ["ssn", "npi", "dl", "license", "email", "vin", "plate", "phone",
                "nysiis_initial", "nysiis_canon_initial", "nysiis_first_missing", "dob_initial",
                "swapped", "sn_last_first", "street"]
BUSINESS_RULES = ["tin", "cnpi", "email", "phone", "rare_word", "lead_word_state", "sn_sorted_name",
                  "street"]
IDENTIFIER_RULES = {"ssn", "npi", "dl", "license", "email", "vin", "plate", "phone", "tin", "cnpi"}
SN_RULES = {"sn_last_first", "sn_sorted_name"}


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
    if rule == "street":
        # added by the build: exact number + street (a changed surname at the same address)
        return _frame(pos, p["addr_street"].to_numpy(dtype=object), st)
    if rule == "dob_initial":
        dob = p["dob"].to_numpy(dtype=object)
        k = np.where((dob != "") & (ini != ""), dob + "|" + ini, "")
        return _frame(pos, k, st)
    if rule == "swapped":
        k = np.where((first != "") & (last != ""), (first + "|" + last) if side == "x" else (last + "|" + first), "")
        return _frame(pos, k, st)
    if rule == "sn_last_first":
        k = np.where(last != "", last + " " + first, "")
        return _frame(pos, k, st)
    al = p["org_aliases"].to_numpy(dtype=object)
    if rule == "rare_word":
        # the rarest word of each alias, and of every alias another record declares as its
        # d/b/a partner (so a trade name meets the legal name)
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
                        rows_p.append(i); rows_k.append(min(w_, key=lambda t: (-rarity.org_idf(t), t)))
        return _frame(np.array(rows_p, dtype=np.int64), np.array(rows_k, dtype=object), st[rows_p] if rows_p else np.array([], dtype=object))
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
    """Keys of every rule for one part, prepared once for all chunks."""

    def __init__(self, xp, wp, part, rarity, cfg, dba_pairs=None):
        self.part, self.cfg = part, cfg
        self.rules = PERSON_RULES if part == "person" else BUSINESS_RULES
        self.bit = {r: 1 << i for i, r in enumerate(self.rules)}
        self.keys, self.report = {}, []
        for r in self.rules:
            xk, wk, rep = plan_rule(rule_keys(xp, part, r, rarity, dba_pairs=dba_pairs),
                                    rule_keys(wp, part, r, rarity, side="w", dba_pairs=dba_pairs), r,
                                    cfg.block_pair_cap)
            rep["part"] = part
            self.report.append(rep)
            sk = None
            if r in SN_RULES:
                sk = np.sort(pd.unique(np.concatenate([xk["key"].to_numpy(dtype=object),
                                                       wk["key"].to_numpy(dtype=object)])).astype(str))
            wkf = pd.DataFrame({"key": wk["key"].to_numpy(dtype=object)})
            self.keys[r] = (xk, wkf, wk["pos"].to_numpy(), sk)
        self.n_x = len(xp)

    def chunk(self, lo, hi):
        """Candidate pairs for extracted parties with positions in [lo, hi): (l, r, rules)."""
        ls, rs, bs = [], [], []
        for r in self.rules:
            xk, wkf, wpos, sk = self.keys[r]
            xc = xk[(xk["pos"] >= lo) & (xk["pos"] < hi)]
            if not len(xc) or not len(wkf):
                continue
            xf = pd.DataFrame({"key": xc["key"].to_numpy(dtype=object)})
            if r in SN_RULES:
                idx = rl.Index()
                idx.add(rl.index.SortedNeighbourhood("key", "key", window=self.cfg.sn_window,
                                                     sorting_key_values=sk))
            else:
                idx = rl.Index()
                idx.add(rl.index.Block("key", "key"))
            mi = idx.index(xf, wkf)
            if len(mi) == 0:
                continue
            li = xc["pos"].to_numpy()[mi.get_level_values(0).to_numpy()]
            ri = wpos[mi.get_level_values(1).to_numpy()]
            ls.append(li); rs.append(ri); bs.append(np.full(len(li), self.bit[r], dtype=np.int64))
        if not ls:
            return pd.DataFrame({"l": np.array([], np.int64), "r": np.array([], np.int64),
                                 "rules": np.array([], np.int64)})
        l = np.concatenate(ls); r_ = np.concatenate(rs); b = np.concatenate(bs)
        key = l * np.int64(1 << 32) + r_
        order = np.argsort(key, kind="stable")
        key, b = key[order], b[order]
        starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        bits = np.bitwise_or.reduceat(b, starts)
        uk = key[starts]
        return pd.DataFrame({"l": uk >> 32, "r": uk & np.int64((1 << 32) - 1), "rules": bits})

    def rule_names(self, bits):
        return [",".join(r for r in self.rules if b & self.bit[r]) for b in bits]
