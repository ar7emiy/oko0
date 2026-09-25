# %% [markdown]
# ### The whole pipeline as one function
#
# `run_pipeline` chains steps 2-16 on two validated input frames and returns every table. The
# Run section below calls the steps one by one so each prints its own output; the self-tests
# call this function on small inputs.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.prepare import *
from wlink.params import *
from wlink.score import *
from wlink.diagnostics import *


def run_pipeline(xdf, wdf, maps, ref, cfg, truth_file=None, log=None):
    log = log or (lambda *a, **k: None)
    pr = prepare(xdf, wdf, maps, ref, cfg, log=log)
    params = estimate_parameters(pr, maps, ref, cfg, wdf, log=log)
    prior, prior_df = estimate_prior(pr, params, cfg, log=log)
    scored = score_all(pr, params, prior, cfg, log=log)
    pairs = pd.concat([pair_table(pr, part, scored[part][0]) for part in ("business", "person")], ignore_index=True)
    entities = rollup_entities(pr, pairs, {part: scored[part][2] for part in ("person", "business")}, cfg)
    claims = rollup_claims(entities, xdf.groupby("claim_id").size())
    evidence = pd.concat([evidence_for(pr, part, pair_table(pr, part, scored[part][0]), scored[part][1],
                                       scored[part][0], params["weights"][part])
                          for part in ("business", "person") if len(scored[part][0])], ignore_index=True)
    diag = diagnostics(pr, scored, pairs, cfg, truth_file, log=log)
    return {"pr": pr, "params": params, "prior": prior, "prior_df": prior_df, "scored": scored, "pairs": pairs,
            "entities": entities, "claims": claims, "evidence": evidence, "diag": diag}
