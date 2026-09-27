## 2 · Normalize

Every column is normalized per `mappings/columns.csv` with the core's normalizers, once per
distinct value (a name that appears 3,000 times is parsed once). Each identifier gets a
validity flag and a reason: NPI Luhn check, VIN check digit, SSN ranges, EIN prefixes,
placeholder values such as 000000000, 123456789 or 1900-01-01. Invalid values stay visible in
the details table and are never compared.

**Where Splink would do better.** Splink leaves cleaning to the user but its comparison
library normalizes inside SQL, in parallel. Here name and address parsing are Python loops
over distinct values; at 1.3M rows they are the second-largest cost after comparisons.