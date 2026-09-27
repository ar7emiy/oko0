SELFTEST, SELFTEST_TEXT = run_selftests(verbosity=1)
print(SELFTEST_TEXT[-3000:])
print(f"self-tests: {SELFTEST.testsRun} run, {len(SELFTEST.failures)} failures, {len(SELFTEST.errors)} errors, "
      f"{len(SELFTEST.skipped)} skipped; matching core v{CORE_VERSION} sha256 {CORE_SHA256}")
assert SELFTEST.wasSuccessful(), "self-tests failed"