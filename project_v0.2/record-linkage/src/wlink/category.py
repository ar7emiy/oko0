# %% [markdown]
# ## 5 · Category
#
# **Extracted rows.** The given category is kept. An inferred category is added beside it,
# with the rule that set it: a valid provider or clinic NPI → medical, a licence type that
# `category_map.csv` maps to medical or legal → that category (both *identifier-backed*); a
# business-name phrase from `category_keywords.csv` → its category (*keyword*, weaker, applied
# to both parts of the row). Witness and claimant are never inferred; "other" counts as no
# information. The category used in matching is identifier-backed → given → keyword.
# A given category that disagrees with an inferred one is a data-quality finding; both stay
# visible.
#
# **Watchlist rows.** No category is given: it is inferred from the specialty, then the licence
# type, through `category_map.csv`; unmapped values → unknown, listed in the manifest.
#
# **Prior group** (from the extracted party): professional (medical, legal), business (repair
# shop, or a business part unless identifier-backed medical/legal), private (witness,
# claimant), unknown.
#
# **Where Splink would do better.** Nothing specific: Splink has no category concept. Its
# closest tool is blocking or training separately per group, which the prior groups mimic.

# %%
from wlink.core import *
from wlink.config import *

GROUPS = ["professional", "business", "private", "unknown"]


def _keyword_rules(kw):
    rules = []
    for phrase, cat in zip(kw["phrase"].map(fold), kw["category"]):
        rules.append((re.compile(r"(?<![A-Z0-9])" + re.escape(phrase) + r"(?![A-Z0-9])"), cat, phrase))
    return rules


def keyword_category(names, kw):
    """First matching phrase wins (file order). Returns (category, phrase) per name."""
    rules = _keyword_rules(kw)

    def one(s):
        s = _undot(fold(s))
        for rx, cat, phrase in rules:
            if rx.search(s):
                return cat, phrase
        return "", ""
    return map_unique(pd.Series(names), one)


def assign_category_extracted(parties, maps):
    cm = maps["category_map"]
    lic = dict(zip(cm.loc[cm["source_field"] == "license_type", "value"].map(fold),
                   cm.loc[cm["source_field"] == "license_type", "category"]))
    p = parties
    given = p["category_given"].where(p["category_given"].isin(
        ["medical", "legal", "repair shop", "witness", "claimant"]), "")
    npi_backed = (p["id_npi"] != "") | (p["id_cnpi"] != "")
    lic_cat = p["license_type"].map(lambda v: lic.get(v, "")).where(p["part"] == "person", "")
    lic_cat = lic_cat.where(lic_cat.isin(["medical", "legal"]), "")
    id_cat = np.where(npi_backed, "medical", lic_cat)
    id_rule = np.where(npi_backed, np.where(p["id_npi"] != "", "provider_npi", "clinic_npi"),
                       np.where(lic_cat != "", "license_type:" + p["license_type"], ""))
    kwc = keyword_category(p["business_raw"], maps["category_keywords"])
    kw_cat = kwc.map(lambda t: t[0]).to_numpy()
    kw_rule = np.where(kw_cat != "", "keyword:" + kwc.map(lambda t: t[1]).to_numpy(), "")
    inferred = np.where(id_cat != "", id_cat, kw_cat)
    inferred_rule = np.where(id_cat != "", id_rule, kw_rule)
    used = np.where(id_cat != "", id_cat, np.where(given != "", given, kw_cat))
    strength = np.where(id_cat != "", "strong", np.where(used != "", "weak", ""))
    used_rule = np.where(id_cat != "", id_rule, np.where(given != "", "given", kw_rule))
    p["category_inferred"] = inferred
    p["category_rule"] = inferred_rule
    p["category"] = used
    p["category_used_rule"] = used_rule
    p["cat_strength"] = strength
    p["category_mismatch"] = (given != "") & (inferred != "") & (given != inferred)
    person = p["part"] == "person"
    group = np.select(
        [person & np.isin(used, ["medical", "legal"]),
         person & np.isin(used, ["witness", "claimant"]),
         person & (used == "repair shop"),
         ~person & (id_cat != "")],
        ["professional", "private", "business", "professional"],
        default=np.where(person, "unknown", "business"))
    p["prior_group"] = group
    return p


def assign_category_watchlist(parties, maps):
    cm = maps["category_map"]
    spec = dict(zip(cm.loc[cm["source_field"] == "specialty", "value"].map(fold),
                    cm.loc[cm["source_field"] == "specialty", "category"]))
    lic = dict(zip(cm.loc[cm["source_field"] == "license_type", "value"].map(fold),
                   cm.loc[cm["source_field"] == "license_type", "category"]))
    p = parties
    raw_spec = p["specialty_raw_row"] if "specialty_raw_row" in p else p["specialty"]
    s_cat = raw_spec.map(lambda v: spec.get(v, ""))
    l_cat = p["license_type"].map(lambda v: lic.get(v, ""))
    cat = np.where(s_cat != "", s_cat, l_cat)
    rule = np.where(s_cat != "", "specialty_map:" + raw_spec, np.where(l_cat != "", "license_type_map:" + p["license_type"], ""))
    p["category_inferred"] = cat
    p["category_rule"] = rule
    p["category"] = cat
    p["category_used_rule"] = rule
    p["cat_strength"] = np.where(cat != "", "strong", "")
    p["category_mismatch"] = False
    p["prior_group"] = ""
    unmapped = pd.concat([
        pd.DataFrame({"source_field": "specialty", "value": raw_spec[(raw_spec != "") & (s_cat == "")]}),
        pd.DataFrame({"source_field": "license_type", "value": p["license_type"][(p["license_type"] != "") & (l_cat == "") & (s_cat == "")]}),
    ]).value_counts().rename("parties").reset_index()
    return p, unmapped
