"""Research modules: corpus-fitted heuristics, kept OUT of the production path.

Nothing in here is imported by the pipeline. These components were tuned
against the synthetic corpus -- their curated word lists, phrase lists and
shape rules encode *our generator's* phrasing, not properties of insurance
notes in general. They are retained so their contribution can still be
measured in an ablation, and so the offline/no-network test harness has a
deterministic stand-in to run against.

Selecting anything here in a production run requires naming it explicitly.
There is no automatic fallback into this package: a missing production
backend raises rather than silently degrading to a corpus-fitted one, because
a silent degradation is indistinguishable in the output from a working model
and quietly invalidates every number measured downstream.
"""
