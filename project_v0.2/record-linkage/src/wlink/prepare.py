# %% [markdown]
# ## 6 · Outside rarity and party frames
#
# The outside tables become a `Rarity` (Census surnames, SSA first names and initials, NPPES
# organization words, with the watchlist's own business-word shares as the larger of the two
# where it is larger) and a `Nicknames` index. Parties are split by part into the positional
# frames the matching core compares, junk identifier values are blanked, and the comparison
# context (value statistics, declared d/b/a pairs) is built.
#
# **Where Splink would do better.** Splink's term-frequency tables come from the data being
# linked; ours come from outside, which is deliberate (a fraud file over-represents exactly the
# names in question) but means rarity is only as good as the Census/SSA/NPPES coverage.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.load import *
from wlink.explode import *
from wlink.category import *


@dataclass
class Prepared:
    X: dict            # part -> positional party frame (extracted)
    W: dict            # part -> positional party frame (watchlist)
    parties: pd.DataFrame
    details: pd.DataFrame
    ties: pd.DataFrame
    vi: pd.DataFrame
    ctx: object
    reports: dict


def split_parts(parties):
    """part -> positional frame, with tie_pos: the tied party's position in the other part's
    frame of the same side (-1 when none)."""
    fr = {part: parties[parties["part"] == part].reset_index(drop=True) for part in ("person", "business")}
    pos = {part: pd.Series(np.arange(len(f)), index=f["party_id"].to_numpy()) for part, f in fr.items()}
    for part, other in (("person", "business"), ("business", "person")):
        t = fr[part]["tie"]
        fr[part]["tie_pos"] = t.map(pos[other]).fillna(-1).astype(np.int64).to_numpy()
    return fr


def rows_to_parties(df, source, maps, nick, params, watchlist):
    rows = normalize_rows(df, maps, nick, params, source)
    parties, details, ties, empty = breakdown(rows, source, nick)
    if watchlist:
        parties, unmapped = assign_category_watchlist(parties, maps)
    else:
        parties = assign_category_extracted(parties, maps)
        unmapped = None
    return rows, parties, details, ties, empty, unmapped


def prepare(xdf, wdf, maps, ref, cfg, log=print):
    """Inputs (validated frames) -> Prepared."""
    p = cfg.core
    nick = Nicknames(ref["nicknames"])
    xrows, xpar, xdet, xtie, xempty, _ = rows_to_parties(xdf, "X", maps, nick, p, False)
    wrows, wpar, wdet, wtie, wempty, unmapped = rows_to_parties(wdf, "W", maps, nick, p, True)
    parties = pd.concat([xpar, wpar], ignore_index=True)
    details = pd.concat([xdet, wdet], ignore_index=True)
    vi = mark_junk(value_index_fast(parties, details), p)
    blanked_x = blank_junk(xpar, vi)
    blanked_w = blank_junk(wpar, vi)
    counts, total = own_org_word_counts(wpar.loc[wpar["part"] == "business", "org_aliases"])
    rarity = Rarity(ref["surnames"], ref["first_names"], ref["org_tokens"], ref["meta"], p,
                    own_org_counts=counts, own_org_total=total)
    stats = build_value_stats(xpar, wpar)
    dba = declared_dba_pairs(pd.concat([xpar["org_aliases"], wpar["org_aliases"]]))
    ctx = CompareContext(params=p, rarity=rarity, nick=nick, stats=stats, dba_pairs=dba)
    X, W = split_parts(xpar), split_parts(wpar)
    dq = details[~details["valid"]].groupby(["type", "reason"]).size().rename("values").reset_index()
    reports = {"empty_rows_extracted": xempty, "empty_rows_watchlist": wempty, "unmapped": unmapped,
               "invalid_values": dq, "junk_blanked": blanked_x + blanked_w,
               "category_mismatch": int(xpar["category_mismatch"].sum()),
               "rarity_source": rarity.source, "nickname_rows": nick.size, "dba_pairs": len(dba),
               "rows": {"extracted": len(xdf), "watchlist": len(wdf)},
               "parties": {f"{s}_{part}": len(fr) for s, d in (("extracted", X), ("watchlist", W))
                           for part, fr in d.items()}}
    log(f"parties: {reports['parties']}  empty rows: extracted {len(xempty)}, watchlist {len(wempty)}")
    log(f"value index: {len(vi):,} values, {int(vi['single_holder'].sum()):,} single-holder, "
        f"{int(vi['junk'].sum()):,} junk; junk values blanked in {reports['junk_blanked']} party fields")
    log(f"rarity: {rarity.source}; nicknames: {nick.size} rows; declared d/b/a pairs: {len(dba)}")
    return Prepared(X=X, W=W, parties=parties, details=details, ties=pd.concat([xtie, wtie]), vi=vi,
                    ctx=ctx, reports=reports)
