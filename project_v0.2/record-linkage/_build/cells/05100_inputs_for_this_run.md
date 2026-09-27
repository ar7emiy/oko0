### Inputs for this run

`synthetic` and `scale` generate their files into `data/` (with a truth file beside them);
`leie` exports the raw LEIE into `data/leie_watchlist.csv` and builds the extracted test set;
`files` reads `RL_EXTRACTED` and `RL_WATCHLIST`. With `IO_FORMAT = "parquet"` the generated
inputs are also written as Parquet and read from there; with `"delta"` both inputs are Delta
tables (section 15a) and their versions are recorded. The truth file is read only by the
diagnostics and self-tests.
