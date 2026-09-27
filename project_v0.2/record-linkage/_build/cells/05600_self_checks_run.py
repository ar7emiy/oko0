SELFCHECK = run_self_checks(XDF, WDF, MAPS, REF, CFG, RUN, log=print, sw=SW) if CFG.self_check else None
if CFG.dataset == "synthetic":
    EDGE = check_edge_cases(PR, PAIRS, ROWS, SCORED, edge_cases())
    print(f"hand-written edge cases: {int(EDGE['ok'].sum())}/{len(EDGE)} expectations met")
    if not EDGE["ok"].all():
        print(EDGE[~EDGE["ok"]].to_string(index=False))
