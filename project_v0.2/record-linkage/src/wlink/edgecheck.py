# %% [markdown]
# ### Edge-case check
#
# Every hand-written case in `edge_cases()` against the run's candidates and entities: the
# expected pair is visible, with the expected basis, veto, rank and levels, and the party carries
# the expected category fields. Used by the diagnostics and by the self-tests.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *


def check_edge_cases(pr, pairs, levels_by_part, scored, entities, edges):
    """One row per expectation: ok / failed with the reason."""
    rows = []
    ent = entities.set_index(["record_id", "part"])
    empty = set(pr.reports["empty_rows_extracted"]["record_id"])
    for c in edges:
        for ex in c["expect"]:
            problems = []
            if ex.get("empty_row"):
                if ex["x"] not in empty:
                    problems.append("not reported as an empty row")
                rows.append({"case": c["case"], "desc": c["desc"], "x": ex["x"], "part": ex["part"], "w": "",
                             "ok": not problems, "problems": "; ".join(problems)})
                continue
            part = ex["part"]
            if ex.get("party"):
                if (ex["x"], part) not in ent.index:
                    problems.append("party missing")
                else:
                    e = ent.loc[(ex["x"], part)]
                    for k, v in ex["party"].items():
                        col = {"category": "category_used"}.get(k, k)
                        got = e[col]
                        if bool(got == v) is False:
                            problems.append(f"{k}={got!r}, expected {v!r}")
            if ex.get("w"):
                P = pairs[(pairs["part"] == part) & (pairs["extracted_record_id"] == ex["x"]) &
                          (pairs["watchlist_record_id"] == ex["w"])]
                if not len(P):
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
                        S, L = scored[part][0], scored[part][1]
                        m = (S["l"].to_numpy() == pr_["_l"]) & (S["r"].to_numpy() == pr_["_r"])
                        lv = L[m].iloc[0]
                        for f, want in ex["levels"].items():
                            code = int(lv[f]) if f in lv else EMPTY
                            got = "empty" if code < 0 else FIELD_LEVELS[f][code]
                            if got != want:
                                problems.append(f"{f} level {got}, expected {want}")
            rows.append({"case": c["case"], "desc": c["desc"], "x": ex["x"], "part": part, "w": ex.get("w", ""),
                         "ok": not problems, "problems": "; ".join(problems)})
    return pd.DataFrame(rows)
