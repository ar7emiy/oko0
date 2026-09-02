"""Entity-intelligence POC source package.

All real logic lives here as importable modules; the notebooks/*.py files
(``# %%`` cell format) are thin orchestration layers that import from this
package and write artifacts to store/. This keeps the pipeline unit-testable and
runnable end-to-end from plain Python.
"""
