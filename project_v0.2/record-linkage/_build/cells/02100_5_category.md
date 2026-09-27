## 5 · Category

**Extracted rows.** The given category is kept. An inferred category is added beside it,
with the rule that set it: a valid provider or clinic NPI → medical, a licence type that
`category_map.csv` maps to medical or legal → that category (both *identifier-backed*); a
business-name phrase from `category_keywords.csv` → its category (*keyword*, weaker, applied
to both parts of the row). Witness and claimant are never inferred; "other" counts as no
information. The category used in matching is identifier-backed → given → keyword.
A given category that disagrees with an inferred one is a data-quality finding; both stay
visible.

**Watchlist rows.** No category is given: it is inferred from the specialty, then the licence
type, through `category_map.csv`; unmapped values → unknown, listed in the manifest.

**Prior group** (from the extracted party): professional (medical, legal), business (repair
shop, or a business part unless identifier-backed medical/legal), private (witness,
claimant), unknown.

**Where Splink would do better.** Nothing specific: Splink has no category concept. Its
closest tool is blocking or training separately per group, which the prior groups mimic.