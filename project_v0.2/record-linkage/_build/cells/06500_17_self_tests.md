## 17 · Self-tests

`unittest` cases for every part of the package (normalizers, breakdown, category, candidates,
comparison levels, score invariants, parameters, output, the LEIE exporter), an end-to-end
run on a small synthetic set with its hand-written edge cases, and the hash check of the
matching core. They run on their own small inputs, so they are the same for every dataset.

**Where Splink would do better.** Splink has a large test suite across DuckDB, Spark and
SQLite backends; these tests cover this package only.