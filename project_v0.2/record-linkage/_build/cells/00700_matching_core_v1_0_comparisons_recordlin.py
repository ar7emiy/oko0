# ---- Matching core v1.1: comparisons (recordlinkage.Compare + custom features) -------------
# One level per field, the same code for candidates, random pairs, anchors and simulated
# pairs. Each feature returns its level codes and, where the level is value-specific, the
# value's own chance-agreement factor `uv` (NaN where the field-level u applies).


@dataclass
class CompareContext:
    params: CoreParams
    rarity: Rarity
    nick: Nicknames
    stats: ValueStats
    dba_pairs: list = field(default_factory=list)      # [(set, set)] declared as one org
    components: dict = field(default_factory=dict)    # random-pair rates for name sub-parts


def _unique_pairs(a, b):
    """Joint factorization of two aligned arrays: (inverse, unique a, unique b)."""
    ca, ua = pd.factorize(np.asarray(a, dtype=object))
    cb, ub = pd.factorize(np.asarray(b, dtype=object))
    nb = len(ub) + 1
    key = ca.astype(np.int64) * nb + cb.astype(np.int64)
    uk, inv = np.unique(key, return_inverse=True)
    return inv, np.asarray(ua, dtype=object)[uk // nb], np.asarray(ub, dtype=object)[uk % nb]


def _arr(s):
    return np.asarray(s.to_numpy() if hasattr(s, "to_numpy") else s, dtype=object)


def _lookup(counts, values):
    """counts: Series value->count. Returns float array (0 where absent)."""
    if counts is None or not len(counts):
        return np.zeros(len(values))
    return pd.Series(values).map(counts).fillna(0).to_numpy(dtype=float)


_JW_CACHE = {}


def _jw(a, b):
    """Jaro-Winkler, memoized: name and org words repeat across millions of pairs."""
    k = (a, b)
    v = _JW_CACHE.get(k)
    if v is None:
        if len(_JW_CACHE) > 5_000_000:
            _JW_CACHE.clear()
        v = _JW_CACHE[k] = jellyfish.jaro_winkler_similarity(a, b)
    return v


_NYSIIS_CACHE = {}
_METAPHONE_CACHE = {}


def _nysiis_c(s):
    v = _NYSIIS_CACHE.get(s)
    if v is None:
        v = _NYSIIS_CACHE[s] = nysiis(s)
    return v


def _metaphone_c(s):
    v = _METAPHONE_CACHE.get(s)
    if v is None:
        t = re.sub(r"[^A-Z]", "", s)
        v = _METAPHONE_CACHE[s] = jellyfish.metaphone(t) if t else ""
    return v


def name_similarity(a, b):
    """The measures one name comparison combines (v1.1): Jaro-Winkler, normalized Levenshtein,
    rapidfuzz token-sort and token-set ratios, and two phonetic codes (NYSIIS, Metaphone)."""
    return {"jaro_winkler": _jw(a, b), "levenshtein": _rf_lev.normalized_similarity(a, b),
            "token_sort": _rf_fuzz.token_sort_ratio(a, b), "token_set": _rf_fuzz.token_set_ratio(a, b),
            "nysiis": bool(a and b and _nysiis_c(a) == _nysiis_c(b)),
            "metaphone": bool(a and b and _metaphone_c(a) and _metaphone_c(a) == _metaphone_c(b))}


LAST_CMP = ["exact", "close", "sound", "differs"]


def _last_cmp(a, b, p):
    """0 exact, 1 close (a spelling variant, a reordered or dropped compound part), 2 sounds
    alike or is moderately similar, 3 differs, -1 empty. Several measures, one graded answer."""
    if not a or not b:
        return -1
    if a == b:
        return 0
    ta, tb = set(re.split(r"[ \-]", a)) - {""}, set(re.split(r"[ \-]", b)) - {""}
    if ta <= tb or tb <= ta:
        return 1
    jw = _jw(a, b)
    lev = _rf_lev.normalized_similarity(a, b)
    if jw >= p.jw_close or lev >= p.lev_close or _rf_fuzz.token_sort_ratio(a, b) >= p.tsr_close:
        return 1
    if (_nysiis_c(a) == _nysiis_c(b) or (_metaphone_c(a) and _metaphone_c(a) == _metaphone_c(b))
            or jw >= p.jw_sound or lev >= p.lev_sound):
        return 2
    return 3


FIRST_CMP = ["exact", "nick", "close", "initial", "empty", "differs"]


def _first_cmp(a, b, p, nick):
    """0 exact, 1 nickname, 2 close (spelling, sound, or one name inside a double name),
    3 initial agrees, 4 empty, 5 differs."""
    if not a or not b:
        return 4
    if len(a) == 1 or len(b) == 1:
        return 3 if a[0] == b[0] else 5
    if a == b:
        return 0
    if nick.roots(a) & nick.roots(b):
        return 1
    if (_jw(a, b) >= p.jw_close or _rf_lev.normalized_similarity(a, b) >= p.lev_close
            or (" " in a or " " in b) and _rf_fuzz.token_set_ratio(a, b) >= 100
            or (_metaphone_c(a) and _metaphone_c(a) == _metaphone_c(b))):
        return 2
    return 5


def _surname_cmp_array(last_l, last_r, p):
    ll, lr = _arr(last_l), _arr(last_r)
    inv, ua, ub = _unique_pairs(ll, lr)
    return np.array([_last_cmp(a, b, p) for a, b in zip(ua, ub)], dtype=np.int8)[inv]


def f_name(first_l, last_l, first_r, last_r, ctx):
    """Person name, one graded group (see FIELD_LEVELS['name'])."""
    p, R = ctx.params, ctx.rarity
    fl, ll, fr, lr = _arr(first_l), _arr(last_l), _arr(first_r), _arr(last_r)
    lc = _surname_cmp_array(ll, lr, p)
    inv, ua, ub = _unique_pairs(fl, fr)
    fc = np.array([_first_cmp(a, b, p, ctx.nick) for a, b in zip(ua, ub)], dtype=np.int8)[inv]
    swapped = (fl != "") & (ll != "") & (fl == lr) & (ll == fr) & (ll != lr)
    last_exact, last_close, last_sound = lc == 0, lc == 1, lc == 2
    first_agree = (fc == 0) | (fc == 1) | (fc == 2)
    conds = [lc < 0, last_exact & (fc == 0), last_exact & (fc == 1), last_exact & (fc == 2), swapped,
             last_close & first_agree, last_sound & first_agree, last_exact & (fc == 3),
             last_exact & (fc == 4), (last_close | last_sound) & ((fc == 3) | (fc == 4)),
             last_exact & (fc == 5)]
    codes = [EMPTY, 0, 1, 2, 6, 3, 4, 5, 7, 8, 9]
    level = np.select(conds, codes, default=10).astype(np.int8)
    # value-specific u: outside tables (and the list's own share) for the agreeing values,
    # random-pair rates for the parts that are not value-specific
    C = ctx.components or {}
    fL = map_unique(pd.Series(lr), R.surname_freq).to_numpy(dtype=float)
    fF = map_unique(pd.Series(fr), lambda v: R.first_freq(v) if v else 1.0).to_numpy(dtype=float)
    ini = map_unique(pd.Series(fr), lambda v: R.initial_share(v) if v else 1.0).to_numpy(dtype=float)
    fLsw = map_unique(pd.Series(fl), R.surname_freq).to_numpy(dtype=float)     # swapped: x.first is w.last
    st = ctx.stats
    own = np.zeros(len(level))
    m0 = level == 0
    if m0.any() and st.ref_n.get("person_name", 0):
        own[m0] = _lookup(st.ref_counts.get("person_name"),
                          (pd.Series(fr[m0]) + " " + pd.Series(lr[m0])).to_numpy()) / st.ref_n["person_name"]
    fuzzy_first = np.where(fc == 0, fF, C.get("first_agrees_fuzzy", np.nan))
    uv = np.full(len(level), np.nan)
    uv = np.where(level == 0, np.maximum(fL * fF, own), uv)
    uv = np.where(level == 1, fL * C.get("first_nick", np.nan), uv)
    uv = np.where(level == 2, fL * C.get("first_close", np.nan), uv)
    uv = np.where(level == 3, C.get("last_close", np.nan) * fuzzy_first, uv)
    uv = np.where(level == 4, C.get("last_sound", np.nan) * fuzzy_first, uv)
    uv = np.where(level == 5, fL * ini, uv)
    uv = np.where(level == 6, fLsw * fF, uv)
    uv = np.where(level == 7, fL * C.get("first_empty", np.nan), uv)
    uv = np.where(level == 9, fL * C.get("first_differs", np.nan), uv)
    return level, uv, fc, lc


def f_middle(ml, ll, mr, lr, ctx):
    """Middle name, compared only when the surnames agree (exact, close or alike): a middle
    name agreeing between two different surnames says nothing, and among pairs whose surnames
    agree its u is taken separately, so the name group is not counted twice."""
    a, b = _arr(ml), _arr(mr)
    lc = _surname_cmp_array(ll, lr, ctx.params)
    empty = (a == "") | (b == "") | (lc < 0) | (lc == 3)
    exact = (a == b) & ~empty & (np.char.str_len(a.astype(str)) > 1)
    ia = np.array([x[:1] for x in a], dtype=object)
    ib = np.array([x[:1] for x in b], dtype=object)
    initial = (ia == ib) & ~empty & ~exact
    level = np.select([empty, exact, initial], [EMPTY, 0, 1], default=2).astype(np.int8)
    return level, np.full(len(level), np.nan)


def _digit_arrays(v, width):
    return np.stack([(v // 10 ** k) % 10 for k in range(width)], axis=1)


def f_dob(dl, dr, ctx):
    a = np.asarray(dl, dtype=np.int64)
    b = np.asarray(dr, dtype=np.int64)
    empty = (a == 0) | (b == 0)
    ya, ma, da = a // 10000, (a // 100) % 100, a % 100
    yb, mb, db = b // 10000, (b // 100) % 100, b % 100
    exact = (a == b) & ~empty
    swap = (ya == yb) & (ma == db) & (da == mb) & ~exact
    hamming = (_digit_arrays(a, 8) != _digit_arrays(b, 8)).sum(axis=1)
    typo = (hamming == 1) & ~exact
    level = np.select([empty, exact, swap | typo, (ya == yb) & (ma == mb), ya == yb],
                      [EMPTY, 0, 1, 2, 3], default=4).astype(np.int8)
    st = ctx.stats
    uv = np.where(level == 0, _lookup(st.ref_counts.get("dob"),
                                      pd.Series(b).map(_dob_str).to_numpy()) / max(1, st.ref_n.get("dob", 0)),
                  np.nan)
    return level, uv


def _dob_str(v):
    v = int(v)
    return f"{v // 10000:04d}-{(v // 100) % 100:02d}-{v % 100:02d}" if v else ""


def f_address(full_l, street_l, zip_l, cs_l, st_l, full_r, street_r, zip_r, cs_r, st_r, ctx):
    fl, sl, zl, cl, tl = (_arr(x) for x in (full_l, street_l, zip_l, cs_l, st_l))
    fr, sr, zr, cr, tr = (_arr(x) for x in (full_r, street_r, zip_r, cs_r, st_r))
    eq = lambda x, y: (x == y) & (x != "")
    comparable = ((tl != "") & (tr != "")) | ((zl != "") & (zr != "")) | ((sl != "") & (sr != ""))
    conds = [eq(fl, fr), eq(sl, sr), eq(zl, zr), eq(cl, cr), eq(tl, tr), comparable]
    level = np.select(conds, [0, 1, 2, 3, 4, 5], default=EMPTY).astype(np.int8)
    st = ctx.stats
    uv = np.full(len(level), np.nan)
    for code, key, vals in ((0, "addr_full", fr), (1, "addr_street", sr), (2, "zip", zr),
                            (3, "city_state", cr), (4, "state", tr)):
        m = level == code
        if m.any():
            uv[m] = _lookup(st.ref_counts.get(key), vals[m]) / max(1, st.ref_n.get(key, 0))
    return level, uv


def _near(a, b):
    """One substituted character or two adjacent ones exchanged (same length)."""
    if len(a) != len(b) or a == b:
        return False
    diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(diff) == 1:
        return True
    return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


def _split_q(v):
    st, _, n = v.partition(":")
    return st, n


def f_identifier(vl, vr, ctx, field_):
    """Exact (value-specific u) / near (typo, for SSN, NPI, DL, TIN) / differs. Qualified
    values (DL, licence, plate: 'STATE:NUMBER') agree when the numbers match and the states
    match or one is unstated. Returns level, uv, veto (two different single-holder values of a
    one-per-party identifier; DL only within one state)."""
    a, b = _arr(vl), _arr(vr)
    n = len(a)
    empty = (a == "") | (b == "")
    qualified = field_ in ("dl", "license", "plate")
    level = np.full(n, EMPTY, dtype=np.int8)
    veto = np.zeros(n, dtype=bool)
    idx = np.flatnonzero(~empty)
    if len(idx):
        inv, ua, ub = _unique_pairs(a[idx], b[idx])
        near_ok = field_ in NEAR_FIELDS
        single = ctx.stats.single.get(field_, set())
        res = []
        for x, y in zip(ua, ub):
            if qualified:
                sx, nx = _split_q(x)
                sy, ny = _split_q(y)
                states_ok = (sx == sy) or not sx or not sy
                if nx == ny and states_ok:
                    res.append((0, False))
                elif near_ok and states_ok and _near(nx, ny):
                    res.append((1, False))
                else:
                    v = (field_ == "dl" and sx and sx == sy and x in single and y in single)
                    res.append((len(FIELD_LEVELS[field_]) - 1, bool(v)))
            else:
                if x == y:
                    res.append((0, False))
                elif near_ok and _near(x, y):
                    res.append((1, False))
                else:
                    v = field_ in VETO_FIELDS and x in single and y in single
                    res.append((len(FIELD_LEVELS[field_]) - 1, bool(v)))
        r = np.array(res, dtype=np.int64).reshape(-1, 2)[inv]
        level[idx] = r[:, 0]
        veto[idx] = r[:, 1].astype(bool)
    st = ctx.stats
    uv = np.full(n, np.nan)
    m = level == 0
    if m.any():
        names = _lookup(st.names.get(field_), b[m])
        refc = _lookup(st.ref_counts.get(field_), b[m])
        uv[m] = np.maximum(np.maximum(names, refc), 1.0) / max(1, st.ref_n.get(field_, 0))
    return level, uv, veto


def f_phone(own_l, row_l, own_r, row_r, ctx):
    """exact_owned_single: the agreeing number is owned on both sides and held under one name;
    exact_shared: agrees otherwise (row-level, or several holders); differs."""
    ol, rwl, orr, rwr = _arr(own_l), _arr(row_l), _arr(own_r), _arr(row_r)
    single = ctx.stats.single.get("phone", set())
    has_l = (ol != "") | (rwl != "")
    has_r = (orr != "") | (rwr != "")
    eq = lambda x, y: (x == y) & (x != "")
    own_own = eq(ol, orr)
    any_eq = own_own | eq(ol, rwr) | eq(rwl, orr) | eq(rwl, rwr)
    own_single = own_own & pd.Series(ol).isin(single).to_numpy()
    level = np.select([~(has_l & has_r), own_single, any_eq], [EMPTY, 0, 1], default=2).astype(np.int8)
    matched = np.where(own_own, ol, np.where(eq(ol, rwr), ol, np.where(eq(rwl, orr), rwl, rwl)))
    st = ctx.stats
    uv = np.full(len(level), np.nan)
    m = (level == 0) | (level == 1)
    if m.any():
        names = _lookup(st.names.get("phone"), matched[m])
        refc = _lookup(st.ref_counts.get("phone"), matched[m])
        uv[m] = np.maximum(np.maximum(names, refc), 1.0) / max(1, st.ref_n.get("phone", 0))
    return level, uv


def f_spec_cat(spec_l, cat_l, str_l, spec_r, cat_r, str_r, ctx):
    """Specialty and category, one correlated group: same specialty / same category, both
    identifier- or mapping-backed / same category, one side given or keyword / different."""
    sl, cl, gl, sr, cr, gr = (_arr(x) for x in (spec_l, cat_l, str_l, spec_r, cat_r, str_r))
    cl = np.where(cl == "other", "", cl)
    cr = np.where(cr == "other", "", cr)
    same_spec = (sl == sr) & (sl != "")
    same_cat = (cl == cr) & (cl != "")
    strong = (gl == "strong") & (gr == "strong")
    comparable = ((cl != "") & (cr != "")) | ((sl != "") & (sr != ""))
    level = np.select([same_spec, same_cat & strong, same_cat, comparable], [0, 1, 2, 3],
                      default=EMPTY).astype(np.int8)
    st = ctx.stats
    uv = np.full(len(level), np.nan)
    m = level == 0
    if m.any():
        uv[m] = _lookup(st.ref_counts.get("specialty"), sr[m]) / max(1, st.ref_n.get("specialty", 0))
    m = (level == 1) | (level == 2)
    if m.any():
        uv[m] = _lookup(st.ref_counts.get("category"), cr[m]) / max(1, st.ref_n.get("category", 0))
    return level, uv


# ---- organization names (goko cell 18, adapted to levels) ----------------------------------
def _rejoin(x, y):
    """goko cell 18: undo OCR splits: 'CASUAL','TY' -> 'CASUALTY' when the other has it."""
    ys, out, i = set(y), [], 0
    while i < len(x):
        if i + 1 < len(x) and x[i] + x[i + 1] in ys and x[i] not in ys:
            out.append(x[i] + x[i + 1]); i += 2
        else:
            out.append(x[i]); i += 1
    return out


def _match_words(x, y, p):
    """goko _org_alias_bits' word pairing: exact first, then Jaro-Winkler >= jw_close.
    Returns (matched words of x, words only in x, words only in y)."""
    x, y = _rejoin(x, y), _rejoin(y, x)
    left, matched = list(y), []
    for t in x:
        hit = t if t in left else max(left, key=lambda u: _jw(t, u), default=None)
        if hit is not None and (hit == t or _jw(t, hit) >= p.jw_close):
            matched.append(t); left.remove(hit)
    only_x = [t for t in x if t not in matched]
    return matched, only_x, left


def _fuzzy_family(a, b, p):
    """goko: one name's words all appear (spelling-tolerant) in the other."""
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return bool(small) and all(any(t == u or _jw(t, u) >= p.jw_close for u in big) for t in small)


def declared_dba_pairs(org_alias_strings):
    """goko cell 18 declared_dbas: alias pairs that one party declares to be one organization
    ('X d/b/a Y'). A trade name shares no words with the legal name; without this the sibling
    level would split a party from its own d/b/a."""
    pairs, seen = [], set()
    for s in org_alias_strings:
        al = [a for a in s.split("|") if a] if s else []
        for i in range(len(al)):
            for j in range(i + 1, len(al)):
                k = (al[i], al[j])
                if k not in seen:
                    seen.add(k)
                    pairs.append((frozenset(al[i].split()), frozenset(al[j].split())))
    return pairs


def _dba_index(ctx):
    """word -> indexes of declared d/b/a pairs using it (built once per context)."""
    idx = getattr(ctx, "_dba_idx", None)
    if idx is None or idx[0] is not ctx.dba_pairs:
        d = defaultdict(set)
        R = ctx.rarity
        for i, (q1, q2) in enumerate(ctx.dba_pairs):
            for q in (q1, q2):
                # index on the side's distinctive words (common ones like MEDICAL would put
                # every declaration in front of every pair); all words when none is distinctive
                rare = [w for w in q if R.org_idf(w) >= 6.0] or list(q)
                for w in rare:
                    d[w].add(i)
        idx = (ctx.dba_pairs, d)
        ctx._dba_idx = idx
    return idx[1]


def _declared_same(xs, ys, ctx):
    """Some record declares the two names to be one organization (goko _declared_same).
    Only declarations sharing a word with each side are checked."""
    if not ctx.dba_pairs:
        return False
    d = _dba_index(ctx)
    cx = set().union(*(d.get(w, set()) for a in xs for w in a))
    cy = set().union(*(d.get(w, set()) for b in ys for w in b))
    p = ctx.params
    for i in sorted(cx & cy):
        q1, q2 = ctx.dba_pairs[i]
        for a in xs:
            for b in ys:
                if (_fuzzy_family(set(a), q1, p) and _fuzzy_family(set(b), q2, p)) or                         (_fuzzy_family(set(a), q2, p) and _fuzzy_family(set(b), q1, p)):
                    return True
    return False


def _org_words_u(words, R):
    """Chance two organizations share these words: the rarest counts in full, the others at
    half, because the words of one name travel together (goko _org_alias_bits)."""
    idfs = sorted((R.org_idf(t) for t in words), reverse=True)
    if not idfs:
        return 1.0
    return 2.0 ** -(idfs[0] + 0.5 * sum(idfs[1:]))


def org_level(al, ar, ctx):
    """(level code, uv, detail) for two '|'-joined alias strings."""
    p, R = ctx.params, ctx.rarity
    if not al or not ar:
        return EMPTY, np.nan, ""
    xs = [a.split() for a in al.split("|") if a]
    ys = [a.split() for a in ar.split("|") if a]
    for x in xs:
        for y in ys:
            if x == y:
                return 0, max(p.u_floor, _org_words_u(y, R)), " ".join(y)
    best = None
    for x in xs:
        for y in ys:
            matched, ox, oy = _match_words(x, y, p)
            score = sum(R.org_idf(t) for t in matched)
            if best is None or score > best[0]:
                best = (score, matched, ox, oy, x, y)
    _, matched, ox, oy, x, y = best
    declared = _declared_same(xs, ys, ctx)
    if declared and not matched:
        return 1, max(p.u_floor, _org_words_u(y, R)), "declared d/b/a"
    if matched and (not ox or not oy):
        return 2, max(p.u_floor, _org_words_u(matched, R)), " ".join(matched)
    dist = lambda ws: [t for t in ws if len(t) >= p.org_distinct_min_len and R.org_idf(t) >= p.org_rare_idf]
    if matched and dist(ox) and dist(oy) and not declared:
        return 6, np.nan, f"{'+'.join(dist(ox))} vs {'+'.join(dist(oy))}"
    if declared:
        return 1, max(p.u_floor, _org_words_u(y, R)), "declared d/b/a"
    if matched:
        # v1.1: word rarity plus token-set similarity. 'close' when most of the rarity weight
        # of both names agrees and the token-set ratio agrees too.
        wm = sum(R.org_idf(t) for t in matched)
        sim = wm / max(wm + sum(R.org_idf(t) for t in ox), wm + sum(R.org_idf(t) for t in oy), 1e-9)
        if sim >= p.org_close_sim and _rf_fuzz.token_set_ratio(" ".join(x), " ".join(y)) >= p.org_close_tsr:
            return 3, max(p.u_floor, _org_words_u(matched, R)), " ".join(matched)
        top = max(matched, key=R.org_idf)
        if R.org_idf(top) >= p.org_rare_idf:
            return 4, max(p.u_floor, 2.0 ** -R.org_idf(top)), top
        return 5, np.nan, " ".join(matched)
    return 7, np.nan, ""


def f_org(al, ar, ctx):
    a, b = _arr(al), _arr(ar)
    inv, ua, ub = _unique_pairs(a, b)
    res = [org_level(x, y, ctx) for x, y in zip(ua, ub)]
    level = np.array([r[0] for r in res], dtype=np.int8)[inv]
    uv = np.array([r[1] for r in res], dtype=float)[inv]
    return level, uv


# Which party-frame columns each feature reads.
FEATURE_COLUMNS = {
    "name": (["first", "last"], ["first", "last"]),
    "middle": (["middle", "last"], ["middle", "last"]),
    "dob": (["dob_int"], ["dob_int"]),
    "address": (["addr_full", "addr_street", "zip", "city_state", "state"],
                ["addr_full", "addr_street", "zip", "city_state", "state"]),
    "phone": (["phone_own", "phone_row"], ["phone_own", "phone_row"]),
    "spec_cat": (["specialty", "category", "cat_strength"], ["specialty", "category", "cat_strength"]),
    "org": (["org_aliases"], ["org_aliases"]),
    **{f: ([f"id_{f}"], [f"id_{f}"]) for f in ["ssn", "npi", "dl", "tin", "license", "email",
                                                "vin", "plate", "cnpi"]},
}


def _feature(field_, ctx):
    if field_ == "name":
        return lambda a, b, c, d: f_name(a, b, c, d, ctx), [field_, f"uv_{field_}", "name_first_cmp", "name_last_cmp"]
    if field_ == "middle":
        return lambda a, b, c, d: f_middle(a, b, c, d, ctx), [field_, f"uv_{field_}"]
    if field_ == "dob":
        return lambda a, b: f_dob(a, b, ctx), [field_, f"uv_{field_}"]
    if field_ == "address":
        return lambda *s: f_address(*s, ctx), [field_, f"uv_{field_}"]
    if field_ == "phone":
        return lambda a, b, c, d: f_phone(a, b, c, d, ctx), [field_, f"uv_{field_}"]
    if field_ == "spec_cat":
        return lambda *s: f_spec_cat(*s, ctx), [field_, f"uv_{field_}"]
    if field_ == "org":
        return lambda a, b: f_org(a, b, ctx), [field_, f"uv_{field_}"]
    return (lambda a, b, f=field_: f_identifier(a, b, ctx, f),
            [field_, f"uv_{field_}", f"veto_{field_}"])


def compare_pairs(left, right, il, ir, part, ctx):
    """Level per field for positional pairs (il into left, ir into right), computed through
    recordlinkage.Compare with one custom vectorized feature per field. Returns a DataFrame
    with one row per pair: `<field>` level codes, `uv_<field>` value-specific u factors,
    `veto_<field>` flags and the name sub-comparisons."""
    il = np.asarray(il, dtype=np.int64)
    ir = np.asarray(ir, dtype=np.int64)
    cols = ["l", "r"]
    if len(il) == 0:
        out = pd.DataFrame({"l": il, "r": ir})
        for f in COMPARED_FIELDS[part]:
            _, labels = _feature(f, ctx)
            for lab in labels:
                out[lab] = pd.Series([], dtype=float if lab.startswith("uv_") else
                                     (bool if lab.startswith("veto_") else np.int8))
        return out
    pairs = pd.MultiIndex.from_arrays([il, ir], names=cols)
    cmp = rl.Compare(indexing_type="position")
    for f in COMPARED_FIELDS[part]:
        func, labels = _feature(f, ctx)
        lcols, rcols = FEATURE_COLUMNS[f]
        cmp.compare_vectorized(func, lcols, rcols, label=labels)
    feats = cmp.compute(pairs, left, right)
    feats = feats.reset_index(drop=True)
    feats.insert(0, "r", ir)
    feats.insert(0, "l", il)
    for c in feats.columns:
        if c in FIELD_LEVELS or c in ("name_first_cmp", "name_last_cmp"):
            feats[c] = feats[c].astype(np.int8)
        elif c.startswith("veto_"):
            feats[c] = feats[c].astype(bool)
    return feats


def coparty_proxy_levels(left, right, il, ir):
    """Co-party level for pairs used in estimation, where business links are not scored yet:
    'anchored' when the two tied businesses share a TIN or clinic NPI. Scoring uses the real
    anchors (business links on an identifier at p >= coparty_min_p, no veto)."""
    tl = left["tie_pos"].to_numpy()[il]
    tr = right["tie_pos"].to_numpy()[ir]
    has = (tl >= 0) & (tr >= 0)
    level = np.full(len(il), EMPTY, dtype=np.int8)
    if has.any():
        agree = np.zeros(int(has.sum()), dtype=bool)
        # v1.1 fix: the tied business's identifiers (tie_tin, tie_cnpi on the person frame);
        # v1.0 read the person frame's own (always empty) TIN columns, so this was never anchored
        for c in ("tie_tin", "tie_cnpi"):
            if c not in left or c not in right:
                continue
            a = left[c].to_numpy()[il][has]
            b = right[c].to_numpy()[ir][has]
            agree |= (a == b) & (a != "")
        level[has] = np.where(agree, 0, 1)
    return level