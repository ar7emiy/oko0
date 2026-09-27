## 3 · Breakdown

Each row yields up to two parties, tied by the row: a **person part** when there is a first
or last name, and a **business part** when there is a business name, or a TIN or clinic NPI
with no business name. Details go to their owner per `mappings/columns.csv`: address and work
phone are held by both parts with ownership `row`; the email goes to the person, or to the
business when the row has no person. Rows that yield no party are reported, never dropped
silently.

**Where Splink would do better.** Splink links records, not parts of records; the split is
ours. What Splink would add is its array comparisons for multi-valued fields (a party with
several phones), which this schema does not need because a row holds one value per column.