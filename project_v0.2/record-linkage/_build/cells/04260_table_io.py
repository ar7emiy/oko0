OUTPUT_KEYS = {  # output table -> key columns of its MERGE
    "entities": ["entity_id"], "rows": ["party_id"], "candidates": ["pair_id"], "evidence": ["pair_id", "field"],
    "claims": ["claim_id"], "dedup_pairs": ["part", "record_id_1", "record_id_2"],
    "weights": ["model", "part", "field", "level"],
}
APPEND_TABLES = {"manifest", "selfcheck_bands", "selfcheck_funnel", "selfcheck_basis", "selfcheck_bins",
                 "baseline_disagreements", "baseline_ambiguity", "run_log"}


def plain_table(df):
    """A frame any writer takes: object columns as text (None -> ''), other dtypes kept."""
    d = df.copy()
    for c in d.columns:
        if d[c].dtype == object or str(d[c].dtype).startswith("str"):
            d[c] = d[c].map(lambda v: "" if v is None or (isinstance(v, float) and v != v) else
                            (v if isinstance(v, str) else (json.dumps(v, default=str) if isinstance(v, (list, dict)) else str(v))))
    d.columns = [str(c) for c in d.columns]
    return d


def row_hashes(df, keys):
    """A hash per row over every column but the run stamp: MERGE updates only changed rows."""
    cols = [c for c in df.columns if c not in ("run_id", "_row_hash")]
    s = pd.util.hash_pandas_object(df[cols].astype(str), index=False)
    return s.astype("uint64").astype(str).to_numpy()


class InMemoryDeltaBackend:
    """Delta Lake semantics in pandas, for tests without Spark: table versions (time travel),
    a change data feed, and MERGE (upsert on keys, delete rows no longer produced)."""

    def __init__(self):
        self.versions = {}      # table -> [DataFrame per version]
        self.cdf = {}           # table -> [DataFrame of changes per version]

    def exists(self, t):
        return t in self.versions

    def latest_version(self, t):
        return len(self.versions[t]) - 1 if t in self.versions else -1

    def read(self, t, version=None):
        v = self.versions[t]
        return v[-1 if version is None else version].copy()

    def _commit(self, t, df, changes):
        self.versions.setdefault(t, []).append(df.reset_index(drop=True))
        self.cdf.setdefault(t, []).append(changes.assign(_commit_version=len(self.versions[t]) - 1))

    def write(self, t, df, mode="overwrite"):
        df = df.reset_index(drop=True)
        if mode == "append" and self.exists(t):
            new = pd.concat([self.read(t), df], ignore_index=True)
            self._commit(t, new, df.assign(_change_type="insert"))
        else:
            old = self.read(t) if self.exists(t) else df.iloc[:0]
            self._commit(t, df, pd.concat([old.assign(_change_type="delete"), df.assign(_change_type="insert")],
                                          ignore_index=True))

    def changes(self, t, start, end=None):
        end = self.latest_version(t) if end is None else end
        parts = [c for c in self.cdf.get(t, []) if start <= int(c["_commit_version"].iloc[0] if len(c) else -1) <= end]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["_change_type", "_commit_version"])

    def merge(self, t, df, keys, delete_missing=True):
        """Upsert df on keys (rows whose _row_hash changed), insert new keys, delete keys absent
        from df (delete_missing). Unchanged rows stay as they were."""
        if not self.exists(t):
            self.write(t, df)
            return {"inserted": len(df), "updated": 0, "deleted": 0}
        old = self.read(t)
        k = lambda d: d[keys].astype(str).agg("\x1f".join, axis=1) if len(d) else pd.Series([], dtype=object)
        ok_, nk = k(old), k(df)
        old_i = pd.Series(np.arange(len(old)), index=ok_.to_numpy())
        new_i = pd.Series(np.arange(len(df)), index=nk.to_numpy())
        common = old_i.index.intersection(new_i.index)
        changed = [c for c in common if old["_row_hash"].iloc[old_i[c]] != df["_row_hash"].iloc[new_i[c]]]
        inserted = new_i.index.difference(old_i.index)
        deleted = old_i.index.difference(new_i.index) if delete_missing else pd.Index([])
        keep_old = old[~ok_.isin(set(changed) | set(deleted)).to_numpy()]
        upd = df[nk.isin(set(changed) | set(inserted)).to_numpy()]
        new = pd.concat([keep_old, upd], ignore_index=True)
        ch = pd.concat([old[ok_.isin(set(changed)).to_numpy()].assign(_change_type="update_preimage"),
                        df[nk.isin(set(changed)).to_numpy()].assign(_change_type="update_postimage"),
                        df[nk.isin(set(inserted)).to_numpy()].assign(_change_type="insert"),
                        old[ok_.isin(set(deleted)).to_numpy()].assign(_change_type="delete")], ignore_index=True)
        self._commit(t, new, ch)
        return {"inserted": len(inserted), "updated": len(changed), "deleted": len(deleted)}

    def history(self, t):
        return pd.DataFrame({"version": np.arange(len(self.versions.get(t, [])))})


class SparkDeltaBackend:
    """The same interface on Databricks (or local Spark with delta-spark). Table names are
    catalog.schema.table, or paths under delta_path_root (delta.`/Volumes/...`)."""

    def __init__(self, spark):
        self.spark = spark

    def _ref(self, t):
        return f"delta.`{t}`" if t.startswith("/") or ":/" in t else t

    def _dt(self, t):
        from delta.tables import DeltaTable
        return DeltaTable.forPath(self.spark, t) if t.startswith("/") or ":/" in t else DeltaTable.forName(self.spark, t)

    def exists(self, t):
        try:
            self.spark.sql(f"DESCRIBE HISTORY {self._ref(t)} LIMIT 1").collect()
            return True
        except Exception:
            return False

    def latest_version(self, t):
        return int(self.spark.sql(f"DESCRIBE HISTORY {self._ref(t)} LIMIT 1").collect()[0]["version"]) if self.exists(t) else -1

    def read(self, t, version=None):
        q = f"SELECT * FROM {self._ref(t)}" + (f" VERSION AS OF {int(version)}" if version is not None else "")
        return self.spark.sql(q).toPandas()

    def changes(self, t, start, end=None):
        r = self.spark.read.format("delta").option("readChangeFeed", "true").option("startingVersion", int(start))
        if end is not None:
            r = r.option("endingVersion", int(end))
        r = r.load(t) if t.startswith("/") or ":/" in t else r.table(t)
        return r.toPandas()

    def write(self, t, df, mode="overwrite"):
        sdf = self.spark.createDataFrame(plain_table(df)) if len(df) else \
            self.spark.createDataFrame(plain_table(df).astype(str))
        w = sdf.write.format("delta").mode(mode).option("overwriteSchema", "true") \
            .option("delta.enableChangeDataFeed", "true")
        w.save(t) if t.startswith("/") or ":/" in t else w.saveAsTable(t)
        if not (t.startswith("/") or ":/" in t):
            self.spark.sql(f"ALTER TABLE {t} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")

    def merge(self, t, df, keys, delete_missing=True):
        if not self.exists(t):
            self.write(t, df)
            return {"inserted": len(df), "updated": 0, "deleted": 0}
        src = self.spark.createDataFrame(plain_table(df))
        cond = " AND ".join(f"t.`{k}` = s.`{k}`" for k in keys)
        m = self._dt(t).alias("t").merge(src.alias("s"), cond) \
            .whenMatchedUpdateAll(condition="t._row_hash <> s._row_hash").whenNotMatchedInsertAll()
        if delete_missing:
            m = m.whenNotMatchedBySourceDelete()
        m.execute()
        last = self.spark.sql(f"DESCRIBE HISTORY {self._ref(t)} LIMIT 1").collect()[0]
        met = last["operationMetrics"] or {}
        return {"inserted": int(met.get("numTargetRowsInserted", 0)), "updated": int(met.get("numTargetRowsUpdated", 0)),
                "deleted": int(met.get("numTargetRowsDeleted", 0))}


def get_spark():
    """The Databricks session (spark), or a local one with delta-spark when installed."""
    g = globals()
    if "spark" in g and g["spark"] is not None:
        return g["spark"]
    from pyspark.sql import SparkSession
    try:
        from delta import configure_spark_with_delta_pip
        b = SparkSession.builder.appName("record-linkage") \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        return configure_spark_with_delta_pip(b).getOrCreate()
    except ImportError:
        return SparkSession.builder.getOrCreate()


class TableIO:
    """Reads the two inputs and writes every output table in the format io_format selects."""

    def __init__(self, cfg, backend=None, run_id=None):
        self.cfg, self.fmt = cfg, cfg.io_format
        self.run_id = run_id or time.strftime("%Y%m%dT%H%M%S")
        self.backend = backend
        if self.fmt == "delta" and backend is None:
            self.backend = SparkDeltaBackend(get_spark())
        self.info = {"io_format": self.fmt, "run_id": self.run_id}
        self.out_dir = cfg.paths["tables"]

    # ---- names ---------------------------------------------------------------------------
    def table(self, name):
        c = self.cfg
        if c.delta_path_root:
            return f"{c.delta_path_root.rstrip('/')}/{name}"
        return ".".join(x for x in (c.delta_catalog, c.delta_schema, name) if x)

    def out_name(self, name):
        return self.table(self.cfg.delta_output_prefix + name) if self.fmt == "delta" else name

    # ---- inputs --------------------------------------------------------------------------
    def read_inputs(self, xpath=None, wpath=None):
        """(extracted frame, report, watchlist frame, report, input metadata)."""
        meta = {}
        if self.fmt == "delta":
            frames = []
            for kind, tname in (("extracted", self.cfg.delta_extracted_table), ("watchlist", self.cfg.delta_watchlist_table)):
                t = self.table(tname)
                v = self.backend.latest_version(t)
                df = self.backend.read(t, v)
                df = df[[c for c in df.columns if not str(c).startswith("_")]].astype(str).replace({"nan": "", "None": ""})
                meta[f"{kind}.table"] = t
                meta[f"{kind}.version"] = int(v)
                frames.append(validate_input(df, kind))
            (x, xr), (w, wr) = frames
            self.info.update(meta)
            return x, xr, w, wr, meta
        reader = (lambda p, s: load_input(p, s)) if self.fmt == "csv" else \
            (lambda p, s: validate_input(pd.read_parquet(p).astype(str).replace({"nan": "", "None": ""}), s))
        x, xr = reader(xpath, "extracted")
        w, wr = reader(wpath, "watchlist")
        meta = {"extracted.path": str(xpath), "watchlist.path": str(wpath),
                "extracted.sha256": sha256_file(xpath), "watchlist.sha256": sha256_file(wpath)}
        self.info.update(meta)
        return x, xr, w, wr, meta

    # ---- outputs -------------------------------------------------------------------------
    def write(self, name, df):
        """Write one output table. Files: overwritten. Delta: MERGE on the table's key (append
        for run-stamped tables), history kept by Delta."""
        d = plain_table(df.drop(columns=[c for c in df.columns if str(c).startswith("_")], errors="ignore"))
        if self.fmt == "csv":
            self.out_dir.mkdir(parents=True, exist_ok=True)
            d.to_csv(self.out_dir / f"{name}.csv", index=False, encoding="utf-8")
            return {"table": name, "rows": len(d)}
        if self.fmt == "parquet":
            self.out_dir.mkdir(parents=True, exist_ok=True)
            d.to_parquet(self.out_dir / f"{name}.parquet", index=False)
            return {"table": name, "rows": len(d)}
        t = self.out_name(name)
        d["run_id"] = self.run_id
        if name in OUTPUT_KEYS:
            keys = OUTPUT_KEYS[name]
            d = d.drop_duplicates(keys, keep="first")
            d["_row_hash"] = row_hashes(d, keys)
            res = self.backend.merge(t, d, keys, delete_missing=True)
        else:
            self.backend.write(t, d, mode="append")
            res = {"appended": len(d)}
        res.update({"table": t, "version": self.backend.latest_version(t)})
        self.info[f"output.{name}"] = json.dumps(res)
        return res
