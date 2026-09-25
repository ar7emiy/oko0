# %% [markdown]
# ## 15 · Workbook and manifest
#
# One Excel workbook, one sheet per table: **entities**, **candidates**, **evidence**,
# **claims**, **manifest**. A table longer than Excel's row limit continues on `name (2)`,
# `name (3)`, ... Every sheet has filters; `basis` and `rests_on_name` are there to filter on,
# never thresholds. The manifest is also written as JSON, and every table as Parquet, beside the
# workbook in gitignored `out/<dataset>/`.
#
# The manifest holds: the run configuration, input and reference hashes, input reports,
# unmapped category values, blocking counts, every m and u with its source, pair count and
# interval, the name sub-part rates, the priors with their counts, recall and flags, the
# sensitivity table, data-quality findings (invalid values, junk values, empty rows, category
# disagreements), vetoes and the timing of each step.
#
# **Where Splink would do better.** Splink writes predictions to a database table or Parquet
# and its model JSON records the trained parameters; it has no workbook. Excel is this
# package's requirement, with its row limit and write time.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *


def manifest_rows(section, df, key_cols, value_col, source_col=None, pairs_col=None, lo=None, hi=None, note_col=None):
    out = []
    for _, r in df.iterrows():
        out.append({"section": section, "key": "|".join(str(r[c]) for c in key_cols),
                    "value": r[value_col], "source": r[source_col] if source_col else "",
                    "pairs": r[pairs_col] if pairs_col else "",
                    "ci_low": r[lo] if lo else "", "ci_high": r[hi] if hi else "",
                    "note": r[note_col] if note_col else ""})
    return out


def _clean_cell(v):
    if v is None:
        return ""
    if isinstance(v, (float, np.floating)):
        if np.isnan(v):
            return ""
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    return v if isinstance(v, (int, float, str)) else str(v)


def write_workbook(path, tables, row_limit, filters=None):
    """tables: ordered {sheet name: DataFrame}. Streams rows (xlsxwriter constant_memory).
    Returns {sheet: [sheet names written]}."""
    import xlsxwriter
    wb = xlsxwriter.Workbook(str(path), {"constant_memory": True, "strings_to_urls": False,
                                         "strings_to_formulas": False, "nan_inf_to_errors": True})
    head = wb.add_format({"bold": True, "bg_color": "#DDE3EA"})
    written = {}
    for name, df in tables.items():
        cols = [str(c) for c in df.columns]
        n = len(df)
        parts = max(1, math.ceil(n / row_limit))
        written[name] = []
        arrays = [df[c].to_numpy() for c in df.columns]
        for k in range(parts):
            sname = name if k == 0 else f"{name} ({k + 1})"
            ws = wb.add_worksheet(sname[:31])
            written[name].append(sname)
            for j, c in enumerate(cols):
                ws.write_string(0, j, c, head)
            lo, hi = k * row_limit, min(n, (k + 1) * row_limit)
            for i in range(lo, hi):
                row = i - lo + 1
                for j, a in enumerate(arrays):
                    v = _clean_cell(a[i])
                    if isinstance(v, str):
                        if v:
                            ws.write_string(row, j, v)
                    elif isinstance(v, bool):
                        ws.write_boolean(row, j, v)
                    else:
                        ws.write_number(row, j, v)
            ws.autofilter(0, 0, max(1, hi - lo), max(0, len(cols) - 1))
            ws.freeze_panes(1, 0)
    wb.close()
    return written


def save_tables(out_dir, tables, manifest):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        d = df.copy()
        for c in d.columns:
            if d[c].dtype == object:
                d[c] = d[c].map(lambda v: "" if v is None else (v if isinstance(v, str) else str(v)))
        d.to_parquet(out_dir / f"{name}.parquet", index=False)
    (out_dir / "manifest.json").write_text(json.dumps(manifest.to_dict("records"), indent=1, default=str),
                                           encoding="utf-8")
