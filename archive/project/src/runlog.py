"""Stage-level run logging, so a pipeline run is watchable instead of silent.

WHY THIS EXISTS
---------------
Every engine in src/ used to return a summary dict and print nothing while it
worked. That is fine for a batch research run and wrong for an operational one:
GLiNER over a few thousand notes, or Splink scoring millions of pairs, would sit
silent for minutes and look hung. Worse, when the resolution post-processing
genuinely WAS pathological (an .iterrows() loop over 2.9M edges, since fixed),
nothing distinguished "slow" from "stuck".

So this is not decoration. Visibility into a long-running stage is how you tell
a working system from a broken one, and the demo is the system running.

DESIGN
------
* ASCII only. Box-drawing characters break on a Windows cp1252 console, which is
  where this actually runs.
* Timestamps and elapsed times, because the point is seeing where time goes.
* Nesting via `step`, so a per-note breakdown sits under its batch.
* `quiet()` for tests, which should not print.

Deliberately not tqdm: a progress bar tells you how far along a loop is, and the
thing worth watching here is WHAT each stage decided -- how many mentions each
extractor found, how many pairs each blocking lane proposed. That is a log, not
a bar.
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager

_ENABLED = True
_DEPTH = 0
_T0: dict[int, float] = {}


def _stdout_utf8() -> None:
    """Windows consoles default to cp1252; a stray non-ASCII char would raise."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


_stdout_utf8()


def enabled(on: bool) -> None:
    global _ENABLED
    _ENABLED = on


@contextmanager
def quiet():
    """Silence logging for the duration (tests, or a stage you already narrated)."""
    global _ENABLED
    prev = _ENABLED
    _ENABLED = False
    try:
        yield
    finally:
        _ENABLED = prev


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def _emit(prefix: str, text: str) -> None:
    if not _ENABLED:
        return
    indent = "  " * _DEPTH
    print(f"{_stamp()}  {indent}{prefix}{text}", flush=True)


def line(text: str) -> None:
    """One log line at the current depth."""
    _emit("", text)


def field(label: str, value) -> None:
    """A labelled detail under the current step, column-aligned for scanning."""
    _emit("", f"{label:<14}{value}")


def note(text: str) -> None:
    """Something the operator should notice but that is not an error."""
    _emit("! ", text)


@contextmanager
def stage(name: str, detail: str = ""):
    """A top-level pipeline stage. Prints on entry and on exit with elapsed time."""
    global _DEPTH
    head = f"[{name}]"
    _emit("", f"{head} {detail}".rstrip())
    _DEPTH += 1
    t = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t
        _DEPTH -= 1
        _emit("", f"{head} done in {dt:.2f}s")


@contextmanager
def step(name: str):
    """A nested unit of work -- typically one document."""
    global _DEPTH
    _emit("", f"{name}")
    _DEPTH += 1
    t = time.perf_counter()
    try:
        yield
    finally:
        _DEPTH -= 1
        _T0[_DEPTH] = time.perf_counter() - t


def every(n: int, i: int, total: int, what: str) -> None:
    """Heartbeat inside a long loop: log on every nth item and on the last.

    For loops whose body is too small to log individually but whose total runtime
    is long enough that silence is indistinguishable from a hang.
    """
    if i == total - 1 or (i % n == 0 and i > 0):
        _emit("", f"{i + 1:>6}/{total}  {what}")
