# ---- Matching core v1.1: outside rarity -----------------------------------------------------
# Ported from goko-v2-poc/goko_v2_poc.ipynb cell "## 16" (surname_freq, first_freq,
# initial_share, org_idf). Change: org_idf takes the larger of NPPES's share and the reference
# population's own share of a word (PLAN.md open question 5), so AUTO or COLLISION, rare among
# NPPES health-care organizations, are not treated as rare in a list full of body shops.

class Rarity:
    """Value-specific chance agreement from outside tables. Tables arrive as dicts
    {value: count} plus the metadata totals; a missing table gives a flat rate that is stamped
    'FLAT' in the source so the run cannot be mistaken for a real one."""

    def __init__(self, surnames=None, first_names=None, org_df=None, meta=None, params=None,
                 own_org_counts=None, own_org_total=0):
        self.p = params or CoreParams()
        meta = meta or {}
        self.surnames, self.firsts, self.org_df = surnames or {}, first_names or {}, org_df or {}
        self.surname_total = meta.get("census", {}).get("people") or max(1, sum(self.surnames.values()))
        self.first_total = meta.get("ssa", {}).get("births") or max(1, sum(self.firsts.values()))
        self.org_n = meta.get("nppes", {}).get("organizations") or 1
        ini = defaultdict(int)
        for n, c in self.firsts.items():
            ini[n[0]] += c
        self.initial = {k: v / self.first_total for k, v in ini.items()}
        self.own_org = own_org_counts or {}
        self.own_org_total = own_org_total
        self.source = {"surnames": "census2010" if self.surnames else "FLAT",
                       "first_names": "ssa1930-2005" if self.firsts else "FLAT",
                       "org_tokens": ("nppes" if (self.org_df and self.org_n > 1) else "FLAT")
                                     + ("+reference_population" if self.own_org_total else "")}
        self._cache_org = {}

    def surname_freq(self, last):
        if not self.surnames:
            return self.p.flat_freq
        parts = [last] + [x for x in re.split(r"[ \-]", last) if x and x != last]
        return min(self.surnames.get(x, self.p.surname_floor) for x in parts) / self.surname_total

    def first_freq(self, first):
        if not self.firsts:
            return self.p.flat_freq
        f = first.split(" ")[0]
        return self.firsts.get(f, self.p.firstname_floor) / self.first_total

    def initial_share(self, letter):
        return self.initial.get(letter[:1], 1 / 26) if self.firsts else 1 / 26

    def org_idf(self, tok):
        """Bits of surprise in two organizations sharing this name word."""
        if tok in self._cache_org:
            return self._cache_org[tok]
        if not (self.org_df and self.org_n > 1):
            idf = 6.0
        else:
            idf = math.log2(self.org_n / self.org_df.get(tok, self.p.org_df_floor))
        if self.own_org_total:
            own = math.log2(self.own_org_total / max(1, self.own_org.get(tok, 0)))
            if self.own_org.get(tok, 0) >= self.p.own_org_min_count:
                idf = min(idf, own)
        self._cache_org[tok] = idf
        return idf


def own_org_word_counts(org_alias_strings):
    """How many parties of the reference population use each org word (for Rarity)."""
    counts = defaultdict(int)
    n = 0
    for s in org_alias_strings:
        if not s:
            continue
        n += 1
        for w in set(" ".join(s.split("|")).split()):
            counts[w] += 1
    return dict(counts), n