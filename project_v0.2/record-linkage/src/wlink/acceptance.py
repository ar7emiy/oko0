# %%
SELFTEST, SELFTEST_TEXT = run_selftests(verbosity=1)
print(SELFTEST_TEXT[-3000:])
print(f"self-tests: {SELFTEST.testsRun} run, {len(SELFTEST.failures)} failures, {len(SELFTEST.errors)} errors, "
      f"{len(SELFTEST.skipped)} skipped; matching core v{CORE_VERSION} sha256 {CORE_SHA256}")
assert SELFTEST.wasSuccessful(), "self-tests failed"

# %% [markdown]
# ## Acceptance (PLAN.md section 5)
#
# Each criterion measured on this run where the dataset allows it: the edge cases and blocking
# recall on `synthetic`, the LEIE targets on `leie`, the time and memory targets on `scale`.
# Nothing here changes a result; it reports.

# %%


def acceptance_table(cfg, diag, sw, pairs, scored, selftest):
    rows = []
    add = lambda c, target, value, met: rows.append({"criterion": c, "target": target, "value": value,
                                                    "met": "yes" if met else ("n/a" if met is None else "NO")})
    add("self-tests pass", "all", f"{selftest.testsRun} run, {len(selftest.failures) + len(selftest.errors)} failing",
        selftest.wasSuccessful())
    total = sw.rows[-1]["elapsed"] if sw.rows else float("nan")
    gen = next((r["elapsed"] for r in sw.rows if r["step"] == "inputs ready"), 0.0)
    total = total - gen          # making the test inputs is not part of a run
    add("input generation / export (not counted)", "-", f"{gen:.0f} s", None)
    truth = {t["part"]: t for t in diag["truth"] if t.get("true_pairs")}
    tp = sum(t["true_pairs"] for t in truth.values())
    prop = sum(t["proposed"] for t in truth.values())
    kept = sum(t["kept"] for t in truth.values())
    rec = prop / tp if tp else float("nan")
    if cfg.dataset == "synthetic":
        add("pipeline time (notebook check < 2 min incl. self-tests: see run_notebook_check.py)", "< 120 s",
            f"{total:.0f} s pipeline", total < 120)
        add("blocking recall on true synthetic pairs", ">= 0.99", f"{rec:.4f} ({prop}/{tp})", rec >= 0.99)
        from_edges = check_edge_cases(PR, PAIRS, None, SCORED, ENTITIES, edge_cases())
        add("every hand-written case: expected basis, veto, top rank", "all",
            f"{int(from_edges['ok'].sum())}/{len(from_edges)}", bool(from_edges["ok"].all()))
    if cfg.dataset == "leie":
        add("LEIE run time", "< 300 s", f"{total:.0f} s", total < 300)
        add("LEIE true pairs proposed", ">= 0.98", f"{rec:.4f} ({prop}/{tp})", rec >= 0.98)
    if cfg.dataset == "scale":
        add("scale run time", "< 3600 s", f"{total:.0f} s", total < 3600)
        add("scale peak memory", "< 10 GB", f"{sw.peak / 1e9:.2f} GB", sw.peak < 10e9)
        add("scale true pairs proposed (diagnostic)", "-", f"{rec:.4f} ({prop}/{tp})", None)
    if tp:
        add("every true pair proposed is visible (kept), incl. name-only", "kept = proposed", f"{kept}/{prop}", kept == prop)
    W_ = pd.concat([PARAMS["weights"]["person"], PARAMS["weights"]["business"]])
    add("every parameter in the manifest with source and count", "all m/u rows",
        f"{len(W_)} level rows, {int((W_['m_chain'] == '').sum())} without m source",
        bool((W_["m_chain"] != "").all() and (W_["u_source"].fillna("") != "").all()))
    add("scored pairs", "-", f"{sum(diag['scored_pairs'].values()):,}", None)
    return pd.DataFrame(rows)


ACCEPTANCE = acceptance_table(CFG, DIAG, SW, PAIRS, SCORED, SELFTEST)
print(ACCEPTANCE.to_string(index=False))
(PATHS["out"] / "acceptance.json").write_text(ACCEPTANCE.to_json(orient="records", indent=1), encoding="utf-8")
